import httpx
import pytest

from app.security.errors import ProviderRateLimitedError, ProviderTimeoutError, RedirectRejectedError
from app.security.gateway import OutboundGateway
from app.security.rate_limit import RetryPolicy

FAST_POLICY = RetryPolicy(
    max_attempts=3, base_delay_seconds=0.001, cap_delay_seconds=0.002, total_budget_seconds=5.0
)


@pytest.mark.asyncio
async def test_redirect_is_rejected_by_default(settings, public_resolver, seeded_deny_list) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://provider.example/elsewhere"})

    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler), resolver=public_resolver, settings=settings, deny_list=seeded_deny_list
    )
    with pytest.raises(RedirectRejectedError):
        await gateway.get(url="https://provider.example/x", allowed_hosts=frozenset({"provider.example"}))


@pytest.mark.asyncio
async def test_429_honors_retry_after_then_succeeds(settings, public_resolver, seeded_deny_list) -> None:
    attempts: list[int] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json={"ok": True})

    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler), resolver=public_resolver, settings=settings, deny_list=seeded_deny_list
    )
    response = await gateway.get(
        url="https://provider.example/x",
        allowed_hosts=frozenset({"provider.example"}),
        retry_policy=FAST_POLICY,
    )
    assert response.status_code == 200
    assert len(attempts) == 2


@pytest.mark.asyncio
async def test_429_exhausting_attempts_raises_rate_limited(settings, public_resolver, seeded_deny_list) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "0"})

    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler), resolver=public_resolver, settings=settings, deny_list=seeded_deny_list
    )
    with pytest.raises(ProviderRateLimitedError):
        await gateway.get(
            url="https://provider.example/x",
            allowed_hosts=frozenset({"provider.example"}),
            retry_policy=FAST_POLICY,
        )


@pytest.mark.asyncio
async def test_5xx_retries_then_succeeds(settings, public_resolver, seeded_deny_list) -> None:
    attempts: list[int] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler), resolver=public_resolver, settings=settings, deny_list=seeded_deny_list
    )
    response = await gateway.get(
        url="https://provider.example/x",
        allowed_hosts=frozenset({"provider.example"}),
        retry_policy=FAST_POLICY,
    )
    assert response.status_code == 200
    assert len(attempts) == 3


@pytest.mark.asyncio
async def test_non_retryable_4xx_fails_on_first_attempt(settings, public_resolver, seeded_deny_list) -> None:
    attempts: list[int] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(404)

    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler), resolver=public_resolver, settings=settings, deny_list=seeded_deny_list
    )
    response = await gateway.get(
        url="https://provider.example/x",
        allowed_hosts=frozenset({"provider.example"}),
        retry_policy=FAST_POLICY,
    )
    # 404 is a valid (non-retryable) terminal response - the gateway returns it
    # and lets the collector decide what a 404 means for that provider.
    assert response.status_code == 404
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_repeated_timeouts_raise_provider_timeout(settings, public_resolver, seeded_deny_list) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout", request=request)

    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler), resolver=public_resolver, settings=settings, deny_list=seeded_deny_list
    )
    with pytest.raises(ProviderTimeoutError):
        await gateway.get(
            url="https://provider.example/x",
            allowed_hosts=frozenset({"provider.example"}),
            retry_policy=FAST_POLICY,
        )
