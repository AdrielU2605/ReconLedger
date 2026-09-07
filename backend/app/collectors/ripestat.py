"""RIPEstat collector (PRD provider matrix: IP/CIDR -> origin ASN, prefix,
holder, routing and registry context).

A single prefix-overview call covers everything the PRD asks for: whether
the resource is currently announced, its origin AS(es) and holder name(s),
related (less-specific) prefixes, and the registry block it falls in
(useful precisely when it is *not* announced - e.g. reserved/documentation
space, as with the fixed verification CIDR 203.0.113.0/24). RIPEstat
accepts a bare IP too and aligns it to the containing announced prefix
itself, so no separate IP-vs-CIDR branching is needed.

Re-checked against stat.ripe.net's own documentation and live responses
(including for 203.0.113.0/24 and a real announced prefix) on 2026-09-07.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.collectors.base import CachePolicy, CollectedFinding, CollectorContext, CollectorMetadata, RatePolicy
from app.collectors.caching import get_cached_findings, store_findings_in_cache
from app.collectors.errors import ProviderSchemaError, ProviderUnavailableError
from app.models.enums import Category, TargetType
from app.security.gateway import parse_json_safely
from app.services.cache import CACHE_STATUS_SUCCESS, compute_cache_key
from app.services.fingerprint import compute_fingerprint

RIPESTAT_HOST = "stat.ripe.net"
PREFIX_OVERVIEW_URL = f"https://{RIPESTAT_HOST}/data/prefix-overview/data.json"
SOURCE_APP = "ReconLedger"

SCHEMA_VERSION = "1"
POSITIVE_TTL_SECONDS = 86400  # PRD FR-05: RDAP/RIPEstat/CT 24 hours
NEGATIVE_TTL_SECONDS = 3600

metadata = CollectorMetadata(
    name="ripestat",
    display_name="RIPEstat",
    supported_targets=frozenset({TargetType.IP, TargetType.CIDR}),
    categories=frozenset({Category.NETWORK_FOOTPRINT}),
    required_credentials=(),
    provider_hosts=frozenset({RIPESTAT_HOST}),
    key_help_url="https://stat.ripe.net/docs/data-api/ripestat-data-api",
    rate_policy=RatePolicy(requests_per_period=5, period_seconds=1, burst=5, concurrency=2),
    cache_policy=CachePolicy(
        positive_ttl_seconds=POSITIVE_TTL_SECONDS, negative_ttl_seconds=NEGATIVE_TTL_SECONDS, schema_version=SCHEMA_VERSION
    ),
)


def _normalize(data: dict[str, Any], queried_resource: str) -> dict[str, Any]:
    asns = [
        {"asn": entry.get("asn"), "holder": entry.get("holder")}
        for entry in (data.get("asns") or [])
        if isinstance(entry, dict)
    ]
    block = data.get("block") or {}
    return {
        "queried_resource": queried_resource,
        "resource": data.get("resource") or queried_resource,
        "announced": bool(data.get("announced")),
        "asns": asns,
        "related_prefixes": data.get("related_prefixes") or [],
        "block_resource": block.get("resource"),
        "block_description": block.get("desc"),
        "block_registry_name": block.get("name"),
    }


def _build_finding(normalized: dict[str, Any], raw: dict[str, Any], source_url: str, target: str) -> CollectedFinding:
    now = datetime.now(timezone.utc)
    if normalized["announced"] and normalized["asns"]:
        holders = "; ".join(
            f"AS{a['asn']} ({a['holder']})" if a.get("holder") else f"AS{a['asn']}" for a in normalized["asns"]
        )
        summary = f"Announced as {normalized['resource']}, originated by {holders}."
    else:
        registry_context = normalized["block_description"] or "no registry block information available"
        summary = f"{normalized['resource']} is not currently announced. Registry block: {registry_context}."

    return CollectedFinding(
        category=Category.NETWORK_FOOTPRINT,
        kind="ripestat.prefix_overview",
        title=f"Routing context for {target}",
        summary=summary,
        normalized_value=normalized,
        raw_evidence=raw,
        source_url=source_url,
        retrieved_at=now,
        fingerprint=compute_fingerprint("ripestat", "ripestat.prefix_overview", {"resource": normalized["resource"]}),
    )


async def run(context: CollectorContext) -> list[CollectedFinding]:
    target = context.target
    cache_key = compute_cache_key(collector="ripestat", schema_version=SCHEMA_VERSION, target_normalized=target.normalized)
    cached_findings = await get_cached_findings(context, cache_key)
    if cached_findings is not None:
        return cached_findings

    url = httpx.URL(PREFIX_OVERVIEW_URL).copy_with(params={"resource": target.normalized, "sourceapp": SOURCE_APP})
    response = await context.gateway.get(url=str(url), allowed_hosts=frozenset({RIPESTAT_HOST}))

    if response.status_code != 200:
        raise ProviderUnavailableError("ripestat", f"unexpected status {response.status_code}")

    body = parse_json_safely(response, host=RIPESTAT_HOST)
    if not isinstance(body, dict):
        raise ProviderSchemaError("ripestat", "response was not a JSON object")

    if body.get("status") != "ok":
        raise ProviderUnavailableError("ripestat", f"API status {body.get('status')!r}")

    data = body.get("data")
    if not isinstance(data, dict):
        raise ProviderSchemaError("ripestat", "response missing a 'data' object")

    normalized = _normalize(data, target.normalized)
    finding = _build_finding(normalized, body, str(url), target.normalized)

    await store_findings_in_cache(
        context.cache, cache_key, [finding], status=CACHE_STATUS_SUCCESS, response_json=body, ttl_seconds=POSITIVE_TTL_SECONDS
    )
    return [finding]
