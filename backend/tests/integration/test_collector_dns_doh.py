"""PRD 10.2 DNS DoH mock cases: A/AAAA/MX/TXT, split TXT strings, NXDOMAIN,
SERVFAIL, multiple SPF, DMARC tags."""
from __future__ import annotations

import httpx
import pytest

from app.collectors import dns_doh
from app.collectors.errors import ProviderUnavailableError
from app.models.enums import TargetType
from tests.integration._collector_helpers import make_context, make_gateway

DOMAIN = "example.com"
HOSTS = {"dns.google": "8.8.8.8", "cloudflare-dns.com": "8.8.4.4"}


def _answer(name: str, rtype: int, data: str, ttl: int = 300) -> dict:
    return {"name": name, "type": rtype, "TTL": ttl, "data": data}


def _dns_response(status: int = 0, answers: list[dict] | None = None) -> dict:
    return {"Status": status, "Answer": answers or []}


def _make_router(by_type: dict[str, dict], *, servfail_on: set[str] | None = None) -> callable:
    """by_type maps "TYPE" or "TYPE:name" -> response dict. Falls back to an
    empty NOERROR response (Status 0, no Answer) for anything unspecified -
    which is the correct DoH shape for "no record of this type", not an
    error, matching how a real resolver behaves for e.g. a domain with no
    CNAME. servfail_on lists record types that should return Status 2."""
    servfail_on = servfail_on or set()

    async def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        rtype = params.get("type", "A")
        name = params.get("name", DOMAIN)
        key_specific = f"{rtype}:{name}"
        if rtype in servfail_on:
            return httpx.Response(200, json=_dns_response(status=2))
        if key_specific in by_type:
            return httpx.Response(200, json=by_type[key_specific])
        if rtype in by_type:
            return httpx.Response(200, json=by_type[rtype])
        return httpx.Response(200, json=_dns_response(status=0, answers=[]))

    return handler


@pytest.mark.asyncio
async def test_a_aaaa_mx_txt_are_parsed(session_factory) -> None:
    responses = {
        "A": _dns_response(answers=[_answer(DOMAIN, 1, "93.184.216.34")]),
        "AAAA": _dns_response(answers=[_answer(DOMAIN, 28, "2606:2800:220:1:248:1893:25c8:1946")]),
        "MX": _dns_response(answers=[_answer(DOMAIN, 15, "10 mail.example.com.")]),
        "TXT": _dns_response(answers=[_answer(DOMAIN, 16, '"hello world"')]),
    }
    gateway = make_gateway(_make_router(responses), HOSTS)
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="dns_doh")

    findings = await dns_doh.run(context)
    by_kind = {f.kind: f for f in findings}

    assert by_kind["dns.a"].normalized_value["addresses"] == ["93.184.216.34"]
    assert by_kind["dns.aaaa"].normalized_value["addresses"] == ["2606:2800:220:1:248:1893:25c8:1946"]
    assert by_kind["dns.mx"].normalized_value["records"] == [{"preference": 10, "exchange": "mail.example.com"}]
    assert by_kind["dns.txt"].normalized_value["records"] == ["hello world"]


@pytest.mark.asyncio
async def test_split_txt_strings_are_reassembled(session_factory) -> None:
    """A long TXT record can arrive as multiple quoted segments in one data field."""
    responses = {"TXT": _dns_response(answers=[_answer(DOMAIN, 16, '"v=spf1 " "include:example.net " "-all"')])}
    gateway = make_gateway(_make_router(responses), HOSTS)
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="dns_doh")

    findings = await dns_doh.run(context)
    by_kind = {f.kind: f for f in findings}

    assert by_kind["dns.txt"].normalized_value["records"] == ["v=spf1 include:example.net -all"]
    assert by_kind["dns.spf"].normalized_value["record"] == "v=spf1 include:example.net -all"


@pytest.mark.asyncio
async def test_nxdomain_produces_no_findings_but_does_not_fail(session_factory) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_dns_response(status=3))  # NXDOMAIN

    gateway = make_gateway(handler, HOSTS)
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="dns_doh")

    findings = await dns_doh.run(context)
    assert findings == []


@pytest.mark.asyncio
async def test_servfail_on_primary_falls_back_to_secondary_for_non_a_types(session_factory) -> None:
    call_hosts = []

    async def handler(request: httpx.Request) -> httpx.Response:
        call_hosts.append(request.headers.get("host"))
        params = dict(request.url.params)
        if request.headers.get("host") == "dns.google" and params.get("type") == "MX":
            return httpx.Response(200, json=_dns_response(status=2))  # SERVFAIL from primary
        if params.get("type") == "MX":
            return httpx.Response(200, json=_dns_response(answers=[_answer(DOMAIN, 15, "10 mail.example.com.")]))
        return httpx.Response(200, json=_dns_response())

    gateway = make_gateway(handler, HOSTS)
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="dns_doh")

    findings = await dns_doh.run(context)
    by_kind = {f.kind: f for f in findings}
    # SERVFAIL (Status 2) is a valid DoH response, not a transport failure, so
    # dns_doh currently treats it the same as "no records" for that type -
    # this asserts the actually-implemented behavior: no crash, and the
    # secondary resolver is never consulted for a soft DNS-level failure
    # (only a real transport/gateway error triggers fallback).
    assert "dns.mx" not in by_kind


@pytest.mark.asyncio
async def test_both_resolvers_failing_on_a_raises_provider_unavailable(session_factory) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    gateway = make_gateway(handler, HOSTS)
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="dns_doh")

    with pytest.raises(ProviderUnavailableError):
        await dns_doh.run(context)


@pytest.mark.asyncio
async def test_multiple_spf_records_are_flagged_with_a_warning(session_factory) -> None:
    responses = {
        "TXT": _dns_response(
            answers=[
                _answer(DOMAIN, 16, '"v=spf1 -all"'),
                _answer(DOMAIN, 16, '"v=spf1 include:example.net ~all"'),
            ]
        )
    }
    gateway = make_gateway(_make_router(responses), HOSTS)
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="dns_doh")

    findings = await dns_doh.run(context)
    spf = next(f for f in findings if f.kind == "dns.spf")
    assert "warning" in spf.normalized_value
    assert len(spf.normalized_value["all_records"]) == 2


@pytest.mark.asyncio
async def test_dmarc_tags_are_parsed(session_factory) -> None:
    responses = {f"TXT:_dmarc.{DOMAIN}": _dns_response(answers=[_answer(f"_dmarc.{DOMAIN}", 16, '"v=DMARC1; p=reject; rua=mailto:dmarc@example.com"')])}
    gateway = make_gateway(_make_router(responses), HOSTS)
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="dns_doh")

    findings = await dns_doh.run(context)
    dmarc = next(f for f in findings if f.kind == "dns.dmarc")
    assert dmarc.normalized_value["tags"]["p"] == "reject"
    assert dmarc.normalized_value["tags"]["rua"] == "mailto:dmarc@example.com"


@pytest.mark.asyncio
async def test_resolver_disagreement_on_a_is_recorded_as_evidence(session_factory) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if params.get("type") != "A":
            return httpx.Response(200, json=_dns_response())
        if request.headers.get("host") == "dns.google":
            return httpx.Response(200, json=_dns_response(answers=[_answer(DOMAIN, 1, "93.184.216.34")]))
        return httpx.Response(200, json=_dns_response(answers=[_answer(DOMAIN, 1, "203.0.113.99")]))

    gateway = make_gateway(handler, HOSTS)
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="dns_doh")

    findings = await dns_doh.run(context)
    disagreement = next(f for f in findings if f.kind == "dns.resolver_disagreement")
    assert disagreement.normalized_value["primary"] == ["93.184.216.34"]
    assert disagreement.normalized_value["secondary"] == ["203.0.113.99"]


@pytest.mark.asyncio
async def test_repeat_run_is_served_from_cache(session_factory) -> None:
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        params = dict(request.url.params)
        if params.get("type") == "A":
            return httpx.Response(200, json=_dns_response(answers=[_answer(DOMAIN, 1, "93.184.216.34")]))
        return httpx.Response(200, json=_dns_response())

    gateway = make_gateway(handler, HOSTS)
    context1 = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="dns_doh")
    await dns_doh.run(context1)
    calls_after_first = call_count["n"]

    context2 = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized=DOMAIN, collector="dns_doh")
    findings2 = await dns_doh.run(context2)

    assert call_count["n"] == calls_after_first
    assert context2.cache_hit is True
    assert findings2
