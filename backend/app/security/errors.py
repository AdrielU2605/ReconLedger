"""Gateway-level typed errors.

These cover failures in the outbound gateway itself (host/destination policy,
response caps, rate limiting). The broader per-collector error taxonomy
(schema errors, auth errors, provider-specific failures) is defined in CP2
alongside the collector plug-in contract and builds on top of these.
"""
from __future__ import annotations


class GatewayError(Exception):
    """Base class for all outbound-gateway failures."""

    safe_error_code = "gateway_error"


class DisallowedHostError(GatewayError):
    """Raised when a request targets a host outside the collector's declared allowlist."""

    safe_error_code = "disallowed_host"

    def __init__(self, host: str) -> None:
        super().__init__(f"Host {host!r} is not on the declared provider allowlist.")
        self.host = host


class BlockedDestinationError(GatewayError):
    """Raised when a resolved destination IP is in a forbidden range or the target deny-list."""

    safe_error_code = "blocked_destination"

    def __init__(self, host: str, ip: str, reason: str) -> None:
        super().__init__(f"Destination {ip} for host {host!r} is blocked: {reason}")
        self.host = host
        self.ip = ip
        self.reason = reason


class RedirectRejectedError(GatewayError):
    """Raised when a provider redirect is disabled or fails hop-by-hop revalidation."""

    safe_error_code = "redirect_rejected"

    def __init__(self, from_url: str, to_url: str, reason: str) -> None:
        super().__init__(f"Redirect from {from_url} to {to_url} rejected: {reason}")
        self.from_url = from_url
        self.to_url = to_url
        self.reason = reason


class ResponseTooLargeError(GatewayError):
    """Raised when a provider response exceeds the configured byte cap."""

    safe_error_code = "response_too_large"

    def __init__(self, host: str, limit_bytes: int) -> None:
        super().__init__(f"Response from {host!r} exceeded the {limit_bytes}-byte cap.")
        self.host = host
        self.limit_bytes = limit_bytes


class MalformedResponseError(GatewayError):
    """Raised when a provider response fails structural/JSON validation limits."""

    safe_error_code = "malformed_response"

    def __init__(self, host: str, detail: str) -> None:
        super().__init__(f"Response from {host!r} is malformed: {detail}")
        self.host = host
        self.detail = detail


class ProviderRateLimitedError(GatewayError):
    """Raised when a provider's rate limit could not be satisfied within budget."""

    safe_error_code = "rate_limited"

    def __init__(self, host: str, retry_after: float | None) -> None:
        super().__init__(f"Provider {host!r} rate-limited the request.")
        self.host = host
        self.retry_after = retry_after


class ProviderTimeoutError(GatewayError):
    """Raised when a provider request exceeds its timeout budget after retries."""

    safe_error_code = "provider_timeout"

    def __init__(self, host: str) -> None:
        super().__init__(f"Provider {host!r} timed out after all retry attempts.")
        self.host = host


class DenyListUnpopulatedError(GatewayError):
    """Raised if any request is attempted before the target deny-list has been seeded.

    PRD FR-03: no collector runs while the deny-list is unpopulated.
    """

    safe_error_code = "deny_list_unpopulated"
