import ipaddress

import httpx
import pytest

from app.security.errors import BlockedDestinationError
from app.security.gateway import OutboundGateway
from app.security.network import IPAddress, StaticResolver, TargetDenyList


@pytest.mark.asyncio
async def test_seed_deny_list_uses_the_gateway_itself_for_doh_resolution(settings) -> None:
    """FR-03 / user amendment 6: the pre-job resolution is an HTTPS request to an
    allowlisted DoH provider through this same gateway, not a raw system DNS call -
    so one mocked httpx transport satisfies both the socket block and the
    resolve-then-seed step."""
    doh_calls: list[str] = []

    async def doh_transport_handler(request: httpx.Request) -> httpx.Response:
        # The transport sees the IP-pinned URL (that's the point of pinning);
        # what we care about here is that the *logical* request - the Host
        # header, path, and query - is still the real DoH provider request.
        doh_calls.append(f"{request.headers.get('host')}{request.url.raw_path.decode()}")
        return httpx.Response(200, json={"Answer": [{"data": "93.184.216.34"}]})

    async def doh_resolve(gateway: OutboundGateway, target_host: str) -> list[IPAddress]:
        response = await gateway.get(
            url=f"https://dns.example/resolve?name={target_host}",
            allowed_hosts=frozenset({"dns.example"}),
        )
        data = response.json()
        return [ipaddress.ip_address(answer["data"]) for answer in data["Answer"]]

    # The resolver used for provider-host validation only needs to know about the
    # DoH host itself for this test; the target's addresses come back through the
    # mocked DoH response body, not through this resolver.
    resolver = StaticResolver(table={"dns.example": [ipaddress.ip_address("8.8.8.8")]})
    deny_list = TargetDenyList()
    gateway = OutboundGateway(
        transport=httpx.MockTransport(doh_transport_handler),
        resolver=resolver,
        settings=settings,
        deny_list=deny_list,
    )

    assert not deny_list.seeded
    await gateway.seed_deny_list("example.com", doh_resolve)

    assert deny_list.seeded
    assert deny_list.contains(ipaddress.ip_address("93.184.216.34"))
    assert doh_calls == ["dns.example/resolve?name=example.com"]


def test_seed_networks_blocks_any_address_within_the_range() -> None:
    """A CIDR target denies the whole range, not just one address, since a
    provider could resolve to any host inside the block the user is
    assessing."""
    deny_list = TargetDenyList()
    deny_list.seed_networks([ipaddress.ip_network("203.0.113.0/24")])

    assert deny_list.seeded
    assert deny_list.contains(ipaddress.ip_address("203.0.113.10"))
    assert deny_list.contains(ipaddress.ip_address("203.0.113.255"))
    assert not deny_list.contains(ipaddress.ip_address("203.0.114.1"))


@pytest.mark.asyncio
async def test_addresses_discovered_later_are_blocked_immediately(settings, public_resolver) -> None:
    deny_list = TargetDenyList()
    deny_list.seed([ipaddress.ip_address("93.184.216.34")])

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must never connect to a newly discovered target address")

    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler), resolver=public_resolver, settings=settings, deny_list=deny_list
    )
    # A collector observes a new target-owned address mid-job (e.g. a CNAME target).
    gateway.note_additional_target_addresses([ipaddress.ip_address("8.8.8.8")])

    with pytest.raises(BlockedDestinationError):
        await gateway.get(url="https://provider.example/x", allowed_hosts=frozenset({"provider.example"}))
