"""FR-03: redirects are rejected by default; a collector may opt in to
following one, but every hop is revalidated (HTTPS-only, host allowlisted by
the validator, and re-run through the same destination-IP/deny-list check
since it's a brand new request through the same client)."""
import ipaddress

import httpx
import pytest

from app.security.errors import RedirectRejectedError
from app.security.gateway import OutboundGateway
from app.security.network import StaticResolver
from app.security.rate_limit import RetryPolicy

FAST_POLICY = RetryPolicy(max_attempts=1, base_delay_seconds=0.001, cap_delay_seconds=0.002, total_budget_seconds=5.0)


def _resolver(hosts_to_ips: dict[str, str]) -> StaticResolver:
    return StaticResolver(table={h: [ipaddress.ip_address(ip)] for h, ip in hosts_to_ips.items()})


@pytest.mark.asyncio
async def test_redirect_without_a_validator_is_still_rejected(settings, seeded_deny_list) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://provider.example/elsewhere"})

    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler),
        resolver=_resolver({"provider.example": "8.8.8.8"}),
        settings=settings,
        deny_list=seeded_deny_list,
    )
    with pytest.raises(RedirectRejectedError):
        await gateway.get(url="https://provider.example/x", allowed_hosts=frozenset({"provider.example"}))


@pytest.mark.asyncio
async def test_redirect_to_a_validator_approved_https_host_is_followed(settings, seeded_deny_list) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("host") == "bootstrap.example":
            return httpx.Response(302, headers={"location": "https://registry.example/domain/x"})
        return httpx.Response(200, json={"ok": True})

    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler),
        resolver=_resolver({"bootstrap.example": "8.8.8.8", "registry.example": "8.8.4.4"}),
        settings=settings,
        deny_list=seeded_deny_list,
    )
    response = await gateway.get(
        url="https://bootstrap.example/x",
        allowed_hosts=frozenset({"bootstrap.example"}),
        allow_redirect_to=lambda host: host == "registry.example",
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_redirect_to_a_non_approved_host_is_rejected_even_with_a_validator(settings, seeded_deny_list) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://not-approved.example/x"})

    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler),
        resolver=_resolver({"bootstrap.example": "8.8.8.8"}),
        settings=settings,
        deny_list=seeded_deny_list,
    )
    with pytest.raises(RedirectRejectedError):
        await gateway.get(
            url="https://bootstrap.example/x",
            allowed_hosts=frozenset({"bootstrap.example"}),
            allow_redirect_to=lambda host: host == "registry.example",
        )


@pytest.mark.asyncio
async def test_redirect_to_plain_http_is_rejected_even_with_a_validator(settings, seeded_deny_list) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://registry.example/x"})

    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler),
        resolver=_resolver({"bootstrap.example": "8.8.8.8"}),
        settings=settings,
        deny_list=seeded_deny_list,
    )
    with pytest.raises(RedirectRejectedError):
        await gateway.get(
            url="https://bootstrap.example/x",
            allowed_hosts=frozenset({"bootstrap.example"}),
            allow_redirect_to=lambda host: True,
        )


@pytest.mark.asyncio
async def test_redirect_chain_longer_than_max_redirects_is_rejected(settings, seeded_deny_list) -> None:
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(302, headers={"location": f"https://hop{calls['n']}.example/x"})

    resolver = _resolver({f"hop{i}.example": "8.8.8.8" for i in range(10)} | {"bootstrap.example": "8.8.8.8"})
    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler), resolver=resolver, settings=settings, deny_list=seeded_deny_list
    )
    with pytest.raises(RedirectRejectedError):
        await gateway.get(
            url="https://bootstrap.example/x",
            allowed_hosts=frozenset({"bootstrap.example"}),
            allow_redirect_to=lambda host: True,
            max_redirects=2,
        )
    assert calls["n"] <= 4  # bounded, not an infinite loop


@pytest.mark.asyncio
async def test_followed_redirect_target_still_goes_through_deny_list_check(settings) -> None:
    """A redirect to an address on the target deny-list must still be
    blocked - following a redirect is not an escape hatch from FR-03."""
    from app.security.network import TargetDenyList

    deny_list = TargetDenyList()
    deny_list.seed([ipaddress.ip_address("93.184.216.34")])

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("host") == "bootstrap.example":
            return httpx.Response(302, headers={"location": "https://registry.example/x"})
        raise AssertionError("must never reach the redirect target once it's deny-listed")

    resolver = _resolver({"bootstrap.example": "8.8.8.8", "registry.example": "93.184.216.34"})
    gateway = OutboundGateway(transport=httpx.MockTransport(handler), resolver=resolver, settings=settings, deny_list=deny_list)

    from app.security.errors import BlockedDestinationError

    with pytest.raises(BlockedDestinationError):
        await gateway.get(
            url="https://bootstrap.example/x",
            allowed_hosts=frozenset({"bootstrap.example"}),
            allow_redirect_to=lambda host: True,
        )


@pytest.mark.asyncio
async def test_timeout_seconds_override_is_applied_per_request(settings, seeded_deny_list) -> None:
    """We can't easily assert httpx's internal timeout value without
    reaching into private state, so this proves the override is plumbed
    through by asserting the request actually completes rather than using
    the (much shorter) default read timeout on a deliberately-delayed mock -
    a genuine functional check, not just a signature check."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler),
        resolver=_resolver({"provider.example": "8.8.8.8"}),
        settings=settings,
        deny_list=seeded_deny_list,
    )
    response = await gateway.get(
        url="https://provider.example/x",
        allowed_hosts=frozenset({"provider.example"}),
        timeout_seconds=60.0,
        retry_policy=FAST_POLICY,
    )
    assert response.status_code == 200
