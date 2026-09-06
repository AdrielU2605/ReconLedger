import ipaddress

import httpx
import pytest

from app.security.errors import BlockedDestinationError
from app.security.gateway import OutboundGateway
from app.security.network import StaticResolver
from tests.conftest import ALLOWED_ADDRESS, DENY_LISTED_ADDRESS


@pytest.mark.asyncio
async def test_resolved_private_address_is_blocked(settings, seeded_deny_list) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must never connect once a resolved address is forbidden")

    resolver = StaticResolver(table={"provider.example": [ipaddress.ip_address("10.0.0.5")]})
    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        settings=settings,
        deny_list=seeded_deny_list,
    )
    with pytest.raises(BlockedDestinationError) as excinfo:
        await gateway.get(url="https://provider.example/x", allowed_hosts=frozenset({"provider.example"}))
    assert "private" in excinfo.value.reason


@pytest.mark.asyncio
async def test_resolved_target_deny_listed_address_is_blocked(settings, seeded_deny_list) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must never connect to an address on the target deny-list")

    resolver = StaticResolver(
        table={"provider.example": [ipaddress.ip_address(DENY_LISTED_ADDRESS)]}
    )
    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        settings=settings,
        deny_list=seeded_deny_list,
    )
    with pytest.raises(BlockedDestinationError) as excinfo:
        await gateway.get(url="https://provider.example/x", allowed_hosts=frozenset({"provider.example"}))
    assert "target" in excinfo.value.reason


@pytest.mark.asyncio
async def test_no_resolved_addresses_is_blocked(settings, seeded_deny_list) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must never connect when resolution returned nothing")

    resolver = StaticResolver(table={"provider.example": []})
    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler),
        resolver=resolver,
        settings=settings,
        deny_list=seeded_deny_list,
    )
    with pytest.raises(BlockedDestinationError):
        await gateway.get(url="https://provider.example/x", allowed_hosts=frozenset({"provider.example"}))


@pytest.mark.asyncio
async def test_allowed_request_is_pinned_to_resolved_ip_with_original_host_header(
    settings, public_resolver, seeded_deny_list
) -> None:
    seen_requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json={"ok": True})

    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler),
        resolver=public_resolver,
        settings=settings,
        deny_list=seeded_deny_list,
    )
    response = await gateway.get(
        url="https://provider.example/path", allowed_hosts=frozenset({"provider.example"})
    )

    assert response.status_code == 200
    assert len(seen_requests) == 1
    pinned = seen_requests[0]
    # The connection target is the resolved IP, not the original hostname...
    assert pinned.url.host == ALLOWED_ADDRESS
    # ...but the Host header and TLS SNI extension still carry the real provider name,
    # so the provider's virtual hosting and certificate validation still work.
    assert pinned.headers.get("host") == "provider.example"
    assert pinned.extensions.get("sni_hostname") == "provider.example"
