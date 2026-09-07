"""RIPEstat collector: announced-prefix, not-announced/reserved-block, and
provider-failure mock cases."""
from __future__ import annotations

import httpx
import pytest

from app.collectors import ripestat
from app.collectors.errors import ProviderSchemaError, ProviderUnavailableError
from app.models.enums import TargetType
from app.security.errors import MalformedResponseError
from tests.integration._collector_helpers import make_context, make_gateway

ANNOUNCED_BODY = {
    "status": "ok",
    "status_code": 200,
    "data": {
        "resource": "8.8.8.0/24",
        "announced": True,
        "asns": [{"asn": 15169, "holder": "GOOGLE - Google LLC"}],
        "related_prefixes": ["8.0.0.0/9"],
        "block": {"resource": "8.0.0.0/8", "desc": "Administered by ARIN", "name": "IANA IPv4 Address Space Registry"},
    },
}

NOT_ANNOUNCED_BODY = {
    "status": "ok",
    "status_code": 200,
    "data": {
        "resource": "203.0.113.0/24",
        "announced": False,
        "asns": [],
        "related_prefixes": [],
        "block": {
            "resource": "203.0.113.0/24",
            "desc": "Documentation (TEST-NET-3) (according to [RFC5737])",
            "name": "IANA IPv4 Special Purpose Address Registry",
        },
    },
}


def _handler_for(body: object, status: int = 200):
    async def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, bytes):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    return handler


@pytest.mark.asyncio
async def test_announced_prefix_reports_origin_asn_and_holder(session_factory) -> None:
    gateway = make_gateway(_handler_for(ANNOUNCED_BODY), {"stat.ripe.net": "8.8.8.8"})
    context = make_context(session_factory, gateway, target_type=TargetType.IP, target_normalized="8.8.8.8", collector="ripestat")

    findings = await ripestat.run(context)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.kind == "ripestat.prefix_overview"
    assert finding.normalized_value["announced"] is True
    assert finding.normalized_value["asns"] == [{"asn": 15169, "holder": "GOOGLE - Google LLC"}]
    assert "AS15169" in finding.summary
    assert "GOOGLE" in finding.summary


@pytest.mark.asyncio
async def test_not_announced_reserved_block_is_reported_not_an_error(session_factory) -> None:
    """The fixed verification CIDR 203.0.113.0/24 is exactly this case:
    not announced, but the registry block context is still useful evidence."""
    gateway = make_gateway(_handler_for(NOT_ANNOUNCED_BODY), {"stat.ripe.net": "8.8.8.8"})
    context = make_context(
        session_factory, gateway, target_type=TargetType.CIDR, target_normalized="203.0.113.0/24", collector="ripestat"
    )

    findings = await ripestat.run(context)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.normalized_value["announced"] is False
    assert finding.normalized_value["asns"] == []
    assert "not currently announced" in finding.summary.lower()
    assert "Documentation (TEST-NET-3)" in finding.summary


@pytest.mark.asyncio
async def test_api_level_error_status_is_a_typed_provider_error(session_factory) -> None:
    gateway = make_gateway(
        _handler_for({"status": "error", "status_code": 500, "data": {}}), {"stat.ripe.net": "8.8.8.8"}
    )
    context = make_context(session_factory, gateway, target_type=TargetType.IP, target_normalized="8.8.8.8", collector="ripestat")

    with pytest.raises(ProviderUnavailableError):
        await ripestat.run(context)


@pytest.mark.asyncio
async def test_missing_data_field_is_a_schema_error(session_factory) -> None:
    gateway = make_gateway(_handler_for({"status": "ok", "status_code": 200}), {"stat.ripe.net": "8.8.8.8"})
    context = make_context(session_factory, gateway, target_type=TargetType.IP, target_normalized="8.8.8.8", collector="ripestat")

    with pytest.raises(ProviderSchemaError):
        await ripestat.run(context)


@pytest.mark.asyncio
async def test_non_200_status_is_a_typed_provider_error(session_factory) -> None:
    gateway = make_gateway(_handler_for({}, status=503), {"stat.ripe.net": "8.8.8.8"})
    context = make_context(session_factory, gateway, target_type=TargetType.IP, target_normalized="8.8.8.8", collector="ripestat")

    with pytest.raises(ProviderUnavailableError):
        await ripestat.run(context)


@pytest.mark.asyncio
async def test_malformed_json_is_a_typed_error_not_a_crash(session_factory) -> None:
    gateway = make_gateway(_handler_for(b"not json"), {"stat.ripe.net": "8.8.8.8"})
    context = make_context(session_factory, gateway, target_type=TargetType.IP, target_normalized="8.8.8.8", collector="ripestat")

    with pytest.raises(MalformedResponseError):
        await ripestat.run(context)


@pytest.mark.asyncio
async def test_repeat_run_is_served_from_cache(session_factory) -> None:
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json=ANNOUNCED_BODY)

    gateway = make_gateway(handler, {"stat.ripe.net": "8.8.8.8"})
    context1 = make_context(session_factory, gateway, target_type=TargetType.IP, target_normalized="8.8.8.8", collector="ripestat")
    findings1 = await ripestat.run(context1)
    assert call_count["n"] == 1

    context2 = make_context(session_factory, gateway, target_type=TargetType.IP, target_normalized="8.8.8.8", collector="ripestat")
    findings2 = await ripestat.run(context2)

    assert call_count["n"] == 1  # no new provider call
    assert context2.cache_hit is True
    assert findings2[0].fingerprint == findings1[0].fingerprint
