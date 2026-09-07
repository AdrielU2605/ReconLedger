"""PRD 10.2 RDAP mock cases: full record, redacted registrant, missing
dates, redirect, 429, malformed JSON."""
from __future__ import annotations

import httpx
import pytest

from app.collectors import rdap
from app.collectors.errors import ProviderUnavailableError
from app.models.enums import TargetType
from app.security.errors import MalformedResponseError, ProviderRateLimitedError
from tests.integration._collector_helpers import make_context, make_gateway

BOOTSTRAP_BODY = {"services": [[["com"], ["https://rdap.example-registry.test/rdap/"]]]}

FULL_RECORD = {
    "handle": "EXAMPLE-HANDLE",
    "ldhName": "example.com",
    "status": ["active"],
    "nameservers": [{"ldhName": "ns1.example.com"}, {"ldhName": "ns2.example.com"}],
    "events": [{"eventAction": "registration", "eventDate": "2000-01-01T00:00:00Z"}],
    "entities": [
        {
            "roles": ["registrar"],
            "vcardArray": ["vcard", [["version", {}, "text", "4.0"], ["fn", {}, "text", "Example Registrar Inc"]]],
        }
    ],
}

REDACTED_RECORD = {
    "ldhName": "example.com",
    "status": ["active"],
    "entities": [
        {"roles": ["registrant"], "vcardArray": ["vcard", [["fn", {}, "text", "REDACTED FOR PRIVACY"]]]},
        {"roles": ["registrar"]},  # no vcardArray at all
    ],
}

MISSING_DATES_RECORD = {"ldhName": "example.com", "status": [], "entities": []}


def _handler_for(record_status_and_body):
    async def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers.get("host")
        path = request.url.path
        if host == "data.iana.org" and path == "/rdap/dns.json":
            return httpx.Response(200, json=BOOTSTRAP_BODY)
        if host == "rdap.example-registry.test" and path == "/rdap/domain/example.com":
            status, body = record_status_and_body
            if isinstance(body, bytes):
                return httpx.Response(status, content=body)
            return httpx.Response(status, json=body)
        raise AssertionError(f"unexpected request to {host}{path}")

    return handler


@pytest.mark.asyncio
async def test_full_record_is_normalized(session_factory) -> None:
    gateway = make_gateway(
        _handler_for((200, FULL_RECORD)),
        {"data.iana.org": "8.8.8.8", "rdap.example-registry.test": "8.8.4.4"},
    )
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="rdap")

    findings = await rdap.run(context)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.kind == "rdap.registration"
    assert finding.normalized_value["registrar"] == "Example Registrar Inc"
    assert finding.normalized_value["nameservers"] == ["ns1.example.com", "ns2.example.com"]
    assert finding.normalized_value["events"]["registration"] == "2000-01-01T00:00:00Z"


@pytest.mark.asyncio
async def test_redacted_registrant_renders_as_not_disclosed_never_an_error(session_factory) -> None:
    gateway = make_gateway(
        _handler_for((200, REDACTED_RECORD)),
        {"data.iana.org": "8.8.8.8", "rdap.example-registry.test": "8.8.4.4"},
    )
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="rdap")

    findings = await rdap.run(context)

    assert len(findings) == 1
    assert findings[0].normalized_value["registrar"] == "not disclosed by registrar"
    registrant = next(e for e in findings[0].normalized_value["entities"] if "registrant" in e["roles"])
    assert registrant["name"] == "not disclosed by registrar"


@pytest.mark.asyncio
async def test_missing_dates_do_not_crash(session_factory) -> None:
    gateway = make_gateway(
        _handler_for((200, MISSING_DATES_RECORD)),
        {"data.iana.org": "8.8.8.8", "rdap.example-registry.test": "8.8.4.4"},
    )
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="rdap")

    findings = await rdap.run(context)

    assert len(findings) == 1
    assert findings[0].normalized_value["events"] == {}
    assert "Registered:" not in findings[0].summary


@pytest.mark.asyncio
async def test_bootstrap_redirect_to_an_approved_registry_host_is_followed(session_factory) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers.get("host")
        path = request.url.path
        if host == "data.iana.org" and path == "/rdap/dns.json":
            return httpx.Response(200, json=BOOTSTRAP_BODY)
        if host == "rdap.example-registry.test" and path == "/rdap/domain/example.com":
            return httpx.Response(302, headers={"location": "https://rdap.example-registry.test/rdap/domain/example.com/"})
        if host == "rdap.example-registry.test" and path == "/rdap/domain/example.com/":
            return httpx.Response(200, json=FULL_RECORD)
        raise AssertionError(f"unexpected request to {host}{path}")

    gateway = make_gateway(handler, {"data.iana.org": "8.8.8.8", "rdap.example-registry.test": "8.8.4.4"})
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="rdap")

    findings = await rdap.run(context)
    assert len(findings) == 1


@pytest.mark.asyncio
async def test_redirect_to_a_host_outside_the_bootstrap_file_is_blocked(session_factory) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers.get("host")
        path = request.url.path
        if host == "data.iana.org" and path == "/rdap/dns.json":
            return httpx.Response(200, json=BOOTSTRAP_BODY)
        if host == "rdap.example-registry.test":
            return httpx.Response(302, headers={"location": "https://not-in-bootstrap.test/domain/example.com"})
        raise AssertionError(f"must never reach {host}{path}")

    gateway = make_gateway(handler, {"data.iana.org": "8.8.8.8", "rdap.example-registry.test": "8.8.4.4"})
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="rdap")

    from app.security.errors import RedirectRejectedError

    with pytest.raises(RedirectRejectedError):
        await rdap.run(context)


@pytest.mark.asyncio
async def test_429_propagates_as_a_typed_error_not_a_crash(session_factory) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers.get("host")
        if host == "data.iana.org":
            return httpx.Response(200, json=BOOTSTRAP_BODY)
        return httpx.Response(429, headers={"retry-after": "0"})

    gateway = make_gateway(handler, {"data.iana.org": "8.8.8.8", "rdap.example-registry.test": "8.8.4.4"})
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="rdap")

    with pytest.raises(ProviderRateLimitedError):
        await rdap.run(context)


@pytest.mark.asyncio
async def test_malformed_json_is_a_typed_error_not_a_crash(session_factory) -> None:
    """rdap.run() lets the gateway's own MalformedResponseError (a
    GatewayError) propagate rather than duplicating the translation the
    runner already does (translate_gateway_error -> ProviderSchemaError,
    tested in the runner's own test suite) - this proves it's typed and
    doesn't crash with a bare JSONDecodeError, not which exact class the
    runner will map it to."""
    gateway = make_gateway(
        _handler_for((200, b"not json at all")),
        {"data.iana.org": "8.8.8.8", "rdap.example-registry.test": "8.8.4.4"},
    )
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="rdap")

    with pytest.raises(MalformedResponseError):
        await rdap.run(context)


@pytest.mark.asyncio
async def test_404_is_an_empty_result_not_an_error(session_factory) -> None:
    gateway = make_gateway(
        _handler_for((404, {"errorCode": 404})),
        {"data.iana.org": "8.8.8.8", "rdap.example-registry.test": "8.8.4.4"},
    )
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="rdap")

    findings = await rdap.run(context)
    assert findings == []


@pytest.mark.asyncio
async def test_no_bootstrap_match_raises_provider_unavailable(session_factory) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"services": []})

    gateway = make_gateway(handler, {"data.iana.org": "8.8.8.8"})
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="rdap")

    with pytest.raises(ProviderUnavailableError):
        await rdap.run(context)


@pytest.mark.asyncio
async def test_repeat_run_is_served_from_cache(session_factory) -> None:
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        host = request.headers.get("host")
        if host == "data.iana.org":
            return httpx.Response(200, json=BOOTSTRAP_BODY)
        return httpx.Response(200, json=FULL_RECORD)

    gateway = make_gateway(handler, {"data.iana.org": "8.8.8.8", "rdap.example-registry.test": "8.8.4.4"})
    context1 = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="rdap")
    findings1 = await rdap.run(context1)
    calls_after_first = call_count["n"]
    assert calls_after_first > 0

    context2 = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="rdap")
    findings2 = await rdap.run(context2)

    assert call_count["n"] == calls_after_first  # no new provider calls
    assert context2.cache_hit is True
    assert findings2[0].fingerprint == findings1[0].fingerprint
