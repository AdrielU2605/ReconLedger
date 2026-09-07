"""The outbound gateway: the single place any network request leaves this process.

FR-03: HTTPS-only, collector-declared host allowlist, redirects disabled by
default, destination IPs validated against forbidden ranges and the per-job
target deny-list, deny-list seeded before any collector runs, every request
carries an identifying User-Agent.
FR-04: bounded exponential backoff with full jitter, Retry-After honored within
budget, retries only on safe idempotent reads.
8.2: response byte caps and typed errors on oversized/malformed JSON.
9 Observability: structured logs with correlation IDs, no raw secrets.

No collector ever receives `httpx.AsyncClient` directly (7.6 design advice) -
only the narrow `get()` method below, which validates the declared provider and
destination before every request.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

import httpx

from app.config import Settings
from app.security.errors import (
    BlockedDestinationError,
    DenyListUnpopulatedError,
    DisallowedHostError,
    MalformedResponseError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    RedirectRejectedError,
    ResponseTooLargeError,
)
from app.security.network import IPAddress, Resolver, SystemResolver, TargetDenyList, is_forbidden_address
from app.security.rate_limit import RetryPolicy, compute_backoff_seconds, parse_retry_after

logger = logging.getLogger("reconledger.gateway")

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
DEFAULT_MAX_RESPONSE_BYTES = 2_000_000


class ValidatingTransport(httpx.AsyncBaseTransport):
    """Wraps a real (or fake, in tests) transport and pins every request to a
    resolved, validated IP address before the inner transport ever sees it.

    This is the "hooks httpx connection establishment" checkpoint: resolution
    and the forbidden-range/deny-list check happen here, immediately before the
    request is handed off, so there is no window between "we checked" and "we
    connected" for DNS to change underneath us. Because every redirect hop is
    re-issued as a brand new request through this same transport (see
    OutboundGateway.get), a followed redirect gets this same validation again.
    """

    def __init__(self, *, inner: httpx.AsyncBaseTransport, resolver: Resolver, deny_list: TargetDenyList) -> None:
        self._inner = inner
        self._resolver = resolver
        self._deny_list = deny_list

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        addresses: list[IPAddress] = await self._resolver.resolve(host)
        if not addresses:
            raise BlockedDestinationError(host, "", "no addresses resolved")
        for address in addresses:
            reason = is_forbidden_address(address)
            if reason:
                raise BlockedDestinationError(host, str(address), reason)
            if self._deny_list.contains(address):
                raise BlockedDestinationError(host, str(address), "assessed target address")

        pinned_address = addresses[0]
        pinned_url = request.url.copy_with(host=str(pinned_address))
        pinned_request = httpx.Request(
            method=request.method,
            url=pinned_url,
            headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": host},
        )
        return await self._inner.handle_async_request(pinned_request)


def _enforce_response_caps(response: httpx.Response, host: str, max_bytes: int) -> None:
    content_length = response.headers.get("content-length")
    if content_length is not None and int(content_length) > max_bytes:
        raise ResponseTooLargeError(host, max_bytes)
    # `.content` is already gzip/deflate/br-decompressed by httpx, so this also
    # enforces the decompressed-byte cap, not just the wire size.
    if len(response.content) > max_bytes:
        raise ResponseTooLargeError(host, max_bytes)


def parse_json_safely(response: httpx.Response, *, host: str) -> Any:
    """Generic structural guard for untrusted provider JSON.

    Per-field/per-shape limits (expected keys, record counts, nesting specific
    to a provider's schema) are enforced by each collector's own parser.
    This function only guarantees the payload is well-formed JSON at all.
    """
    try:
        return json.loads(response.content)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MalformedResponseError(host, str(exc)) from exc


DohResolveFn = Callable[["OutboundGateway", str], Awaitable[list[IPAddress]]]
RedirectHostValidator = Callable[[str], bool]


class _FollowRedirect(Exception):
    """Internal control-flow signal only - never escapes OutboundGateway.get()."""

    def __init__(self, location: str) -> None:
        self.location = location


class OutboundGateway:
    """The only object in the codebase that may issue an outbound HTTP request."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport,
        resolver: Resolver,
        settings: Settings,
        deny_list: TargetDenyList | None = None,
    ) -> None:
        self._settings = settings
        self._deny_list = deny_list or TargetDenyList()
        self._transport = ValidatingTransport(inner=transport, resolver=resolver, deny_list=self._deny_list)
        self._client = httpx.AsyncClient(
            transport=self._transport,
            follow_redirects=False,
            timeout=httpx.Timeout(
                connect=settings.connect_timeout_seconds,
                read=settings.default_request_timeout_seconds,
                write=settings.default_request_timeout_seconds,
                pool=settings.default_request_timeout_seconds,
            ),
        )
        # True only for the duration of the pre-job DoH resolution itself (see
        # seed_deny_list): that request necessarily happens before the deny-list
        # exists, so it is the one exempt case for the "deny-list must be
        # seeded" guard in get(). It is never set by, or exposed to, collectors.
        self._bootstrapping = False

    @property
    def deny_list(self) -> TargetDenyList:
        return self._deny_list

    async def seed_deny_list(self, target_host: str, doh_resolve: DohResolveFn) -> None:
        """Pre-job resolution step (FR-03). `doh_resolve` performs its own request
        through this same gateway against an allowlisted DoH host, so the
        resolution itself is subject to the same allowlist/retry/logging policy
        as any other provider call."""
        self._bootstrapping = True
        try:
            addresses = await doh_resolve(self, target_host)
        finally:
            self._bootstrapping = False
        self._deny_list.seed(addresses)
        logger.info("deny_list_seeded", extra={"host": target_host})

    def note_additional_target_addresses(self, addresses: list[IPAddress]) -> None:
        """Addresses discovered later in the job are added immediately (FR-03)."""
        self._deny_list.add(addresses)

    async def get(
        self,
        *,
        url: str,
        allowed_hosts: frozenset[str],
        headers: dict[str, str] | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        retry_policy: RetryPolicy | None = None,
        timeout_seconds: float | None = None,
        allow_redirect_to: RedirectHostValidator | None = None,
        max_redirects: int = 5,
    ) -> httpx.Response:
        """Perform a validated, retried, rate-aware GET. This is the only request
        method exposed for MVP collectors, all of which are read-only.

        Redirects are rejected by default (FR-03). Passing `allow_redirect_to`
        lets a collector opt in for exactly the case PRD 8.1 describes (e.g.
        RDAP bootstrap results) - each hop is revalidated: HTTPS-only, the new
        host must pass the validator, and it goes through the same
        destination-IP/deny-list check as any other request, since it is
        re-issued as a brand new request through this same client.
        """
        if not self._deny_list.seeded and not self._bootstrapping:
            raise DenyListUnpopulatedError()

        current_url = url
        host = httpx.URL(current_url).host
        if host not in allowed_hosts:
            raise DisallowedHostError(host)

        policy = retry_policy or RetryPolicy(
            max_attempts=self._settings.retry_max_attempts,
            base_delay_seconds=self._settings.retry_base_delay_seconds,
            cap_delay_seconds=self._settings.retry_cap_delay_seconds,
        )
        request_headers = {"User-Agent": self._settings.user_agent, **(headers or {})}
        request_timeout = (
            httpx.Timeout(
                connect=self._settings.connect_timeout_seconds,
                read=timeout_seconds,
                write=timeout_seconds,
                pool=timeout_seconds,
            )
            if timeout_seconds is not None
            else None
        )
        start = time.monotonic()
        redirects_followed = 0

        while True:
            try:
                return await self._request_with_retries(
                    current_url, host, request_headers, max_response_bytes, policy, request_timeout, start,
                    allow_redirects=allow_redirect_to is not None,
                )
            except _FollowRedirect as redirect:
                next_url = httpx.URL(current_url).join(redirect.location)
                if (
                    allow_redirect_to is None
                    or redirects_followed >= max_redirects
                    or next_url.scheme != "https"
                    or not allow_redirect_to(next_url.host)
                ):
                    raise RedirectRejectedError(
                        current_url, redirect.location, "redirect target not allowed or max redirects exceeded"
                    ) from None
                redirects_followed += 1
                current_url = str(next_url)
                host = next_url.host

    async def _request_with_retries(
        self,
        url: str,
        host: str,
        request_headers: dict[str, str],
        max_response_bytes: int,
        policy: RetryPolicy,
        request_timeout: httpx.Timeout | None,
        start: float,
        *,
        allow_redirects: bool,
    ) -> httpx.Response:
        last_exception: Exception | None = None

        for attempt in range(1, policy.max_attempts + 1):
            if time.monotonic() - start > policy.total_budget_seconds:
                break
            attempt_start = time.monotonic()
            try:
                if request_timeout is not None:
                    response = await self._client.get(url, headers=request_headers, timeout=request_timeout)
                else:
                    response = await self._client.get(url, headers=request_headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exception = exc
                logger.warning(
                    "provider_request_failed",
                    extra={"host": host, "attempt": attempt, "safe_error_code": "transport_error"},
                )
                if attempt < policy.max_attempts:
                    await asyncio.sleep(compute_backoff_seconds(attempt, policy))
                    continue
                raise ProviderTimeoutError(host) from exc

            latency_ms = (time.monotonic() - attempt_start) * 1000
            logger.info(
                "provider_request",
                extra={"host": host, "attempt": attempt, "latency_ms": latency_ms, "cache_outcome": "miss"},
            )

            if response.status_code in _REDIRECT_STATUS_CODES:
                if allow_redirects:
                    raise _FollowRedirect(response.headers.get("location", ""))
                raise RedirectRejectedError(url, response.headers.get("location", ""), "redirects disabled by default")

            if response.status_code == 429:
                retry_after = parse_retry_after(response.headers.get("retry-after"))
                if attempt >= policy.max_attempts:
                    raise ProviderRateLimitedError(host, retry_after)
                delay = retry_after if retry_after is not None else compute_backoff_seconds(attempt, policy)
                if time.monotonic() - start + delay > policy.total_budget_seconds:
                    raise ProviderRateLimitedError(host, retry_after)
                await asyncio.sleep(delay)
                continue

            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < policy.max_attempts:
                await asyncio.sleep(compute_backoff_seconds(attempt, policy))
                continue

            _enforce_response_caps(response, host, max_response_bytes)
            return response

        if last_exception is not None:
            raise ProviderTimeoutError(host) from last_exception
        raise ProviderTimeoutError(host)

    async def aclose(self) -> None:
        await self._client.aclose()


def build_production_gateway(settings: Settings) -> OutboundGateway:
    """One real gateway per job, using the real system resolver for provider
    hosts and a real httpx transport. Never constructed by, or exposed to,
    collectors directly - only the job runner builds these."""
    return OutboundGateway(
        transport=httpx.AsyncHTTPTransport(),
        resolver=SystemResolver(),
        settings=settings,
    )
