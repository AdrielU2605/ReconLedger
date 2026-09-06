import httpx
import pytest

from app.security.errors import DenyListUnpopulatedError, DisallowedHostError
from app.security.gateway import OutboundGateway
from app.security.network import TargetDenyList


def _mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_deny_list_must_be_seeded_before_any_request(settings, public_resolver) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the inner transport must never be reached before the deny-list is seeded")

    gateway = OutboundGateway(
        transport=_mock_transport(handler),
        resolver=public_resolver,
        settings=settings,
        deny_list=TargetDenyList(),
    )
    with pytest.raises(DenyListUnpopulatedError):
        await gateway.get(url="https://provider.example/x", allowed_hosts=frozenset({"provider.example"}))


@pytest.mark.asyncio
async def test_host_outside_allowlist_is_rejected(settings, public_resolver, seeded_deny_list) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the inner transport must never be reached for a disallowed host")

    gateway = OutboundGateway(
        transport=_mock_transport(handler),
        resolver=public_resolver,
        settings=settings,
        deny_list=seeded_deny_list,
    )
    with pytest.raises(DisallowedHostError):
        await gateway.get(
            url="https://provider.example/x",
            allowed_hosts=frozenset({"a-different-provider.example"}),
        )


@pytest.mark.asyncio
async def test_every_request_carries_identifying_user_agent(settings, public_resolver, seeded_deny_list) -> None:
    seen_user_agents: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_user_agents.append(request.headers.get("user-agent", ""))
        return httpx.Response(200, json={"ok": True})

    gateway = OutboundGateway(
        transport=_mock_transport(handler),
        resolver=public_resolver,
        settings=settings,
        deny_list=seeded_deny_list,
    )
    await gateway.get(url="https://provider.example/x", allowed_hosts=frozenset({"provider.example"}))

    assert len(seen_user_agents) == 1
    assert settings.app_name in seen_user_agents[0]
    assert settings.repository_url in seen_user_agents[0]
