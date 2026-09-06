import httpx
import pytest

from app.security.errors import MalformedResponseError, ResponseTooLargeError
from app.security.gateway import OutboundGateway, parse_json_safely


@pytest.mark.asyncio
async def test_oversized_content_length_is_rejected(settings, public_resolver, seeded_deny_list) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-length": "999999999"}, json={"ok": True})

    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler), resolver=public_resolver, settings=settings, deny_list=seeded_deny_list
    )
    with pytest.raises(ResponseTooLargeError):
        await gateway.get(
            url="https://provider.example/x",
            allowed_hosts=frozenset({"provider.example"}),
            max_response_bytes=1000,
        )


@pytest.mark.asyncio
async def test_oversized_actual_body_is_rejected_even_without_content_length(
    settings, public_resolver, seeded_deny_list
) -> None:
    big_payload = "x" * 5000

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=big_payload)

    gateway = OutboundGateway(
        transport=httpx.MockTransport(handler), resolver=public_resolver, settings=settings, deny_list=seeded_deny_list
    )
    with pytest.raises(ResponseTooLargeError):
        await gateway.get(
            url="https://provider.example/x",
            allowed_hosts=frozenset({"provider.example"}),
            max_response_bytes=1000,
        )


def test_parse_json_safely_rejects_malformed_body() -> None:
    response = httpx.Response(200, content=b"{not valid json")
    with pytest.raises(MalformedResponseError):
        parse_json_safely(response, host="provider.example")


def test_parse_json_safely_accepts_valid_body() -> None:
    response = httpx.Response(200, json={"a": 1})
    assert parse_json_safely(response, host="provider.example") == {"a": 1}
