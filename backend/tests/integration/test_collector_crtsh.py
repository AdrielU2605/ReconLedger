"""PRD 10.2 crt.sh mock cases: duplicates, wildcard/newline names, IDNA,
unrelated SAN, expired cert, HTML error."""
from __future__ import annotations

import httpx
import pytest

from app.collectors import crtsh
from app.collectors.errors import ProviderSchemaError
from app.models.enums import TargetType
from app.security.errors import MalformedResponseError
from tests.integration._collector_helpers import make_context, make_gateway

DOMAIN = "example.com"
HOSTS = {"crt.sh": "8.8.8.8"}


def _cert(id_, name_value, issuer="Example CA", not_before="2020-01-01T00:00:00", not_after="2021-01-01T00:00:00") -> dict:
    return {
        "id": id_,
        "issuer_ca_id": 1,
        "issuer_name": issuer,
        "common_name": name_value.split("\n")[0],
        "name_value": name_value,
        "entry_timestamp": not_before,
        "not_before": not_before,
        "not_after": not_after,
    }


def _gateway_for(certs: list[dict]) -> object:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=certs)

    return make_gateway(handler, HOSTS)


@pytest.mark.asyncio
async def test_duplicates_across_certs_are_merged_into_one_finding(session_factory) -> None:
    certs = [_cert(1, "www.example.com"), _cert(2, "www.example.com")]
    gateway = _gateway_for(certs)
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="crtsh")

    findings = await crtsh.run(context)

    assert len(findings) == 1
    assert findings[0].normalized_value["subdomain"] == "www.example.com"
    assert findings[0].normalized_value["cert_count"] == 2
    assert set(findings[0].normalized_value["cert_ids"]) == {1, 2}


@pytest.mark.asyncio
async def test_wildcard_and_newline_separated_names_are_parsed(session_factory) -> None:
    certs = [_cert(1, "*.example.com\nwww.example.com\nexample.com")]
    gateway = _gateway_for(certs)
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="crtsh")

    findings = await crtsh.run(context)
    by_name = {f.normalized_value["subdomain"]: f for f in findings}

    assert set(by_name) == {"example.com", "www.example.com"}
    assert by_name["example.com"].normalized_value["wildcard"] is True


@pytest.mark.asyncio
async def test_idna_name_is_normalized(session_factory) -> None:
    certs = [_cert(1, "münchen.example.com")]
    gateway = _gateway_for(certs)
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="crtsh")

    findings = await crtsh.run(context)
    assert len(findings) == 1
    assert findings[0].normalized_value["subdomain"].startswith("xn--")
    assert findings[0].normalized_value["subdomain"].endswith(".example.com")


@pytest.mark.asyncio
async def test_unrelated_san_outside_registrable_domain_is_excluded(session_factory) -> None:
    certs = [_cert(1, "www.example.com\nwww.totally-unrelated.test")]
    gateway = _gateway_for(certs)
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="crtsh")

    findings = await crtsh.run(context)
    names = {f.normalized_value["subdomain"] for f in findings}
    assert names == {"www.example.com"}


@pytest.mark.asyncio
async def test_expired_certificate_is_still_retained_as_historical_evidence(session_factory) -> None:
    certs = [_cert(1, "old.example.com", not_before="2010-01-01T00:00:00", not_after="2011-01-01T00:00:00")]
    gateway = _gateway_for(certs)
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="crtsh")

    findings = await crtsh.run(context)
    assert len(findings) == 1
    assert findings[0].normalized_value["not_after_max"] == "2011-01-01T00:00:00"


@pytest.mark.asyncio
async def test_html_error_page_is_a_typed_error_not_a_crash(session_factory) -> None:
    """See the equivalent RDAP test: the collector lets the gateway's own
    MalformedResponseError propagate rather than re-wrapping it itself."""
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html><body>Error: too busy</body></html>", headers={"content-type": "text/html"})

    gateway = make_gateway(handler, HOSTS)
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="crtsh")

    with pytest.raises(MalformedResponseError):
        await crtsh.run(context)


@pytest.mark.asyncio
async def test_non_array_json_response_is_a_provider_schema_error(session_factory) -> None:
    """Unlike the malformed-JSON case, this IS a collector-level check
    (crtsh.py's own isinstance(data, list) guard), since valid-but-wrong-
    shape JSON is specific to what this collector expects, not something
    the generic gateway parser can know about."""
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "not an array"})

    gateway = make_gateway(handler, HOSTS)
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="crtsh")

    with pytest.raises(ProviderSchemaError):
        await crtsh.run(context)


@pytest.mark.asyncio
async def test_empty_result_is_cached_as_empty_not_success(session_factory) -> None:
    gateway = _gateway_for([])
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="crtsh")

    findings = await crtsh.run(context)
    assert findings == []


@pytest.mark.asyncio
async def test_repeat_run_is_served_from_cache(session_factory) -> None:
    call_count = {"n": 0}
    certs = [_cert(1, "www.example.com")]

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json=certs)

    gateway = make_gateway(handler, HOSTS)
    context1 = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="crtsh")
    findings1 = await crtsh.run(context1)

    context2 = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="crtsh")
    findings2 = await crtsh.run(context2)

    assert call_count["n"] == 1
    assert context2.cache_hit is True
    assert findings2[0].fingerprint == findings1[0].fingerprint
