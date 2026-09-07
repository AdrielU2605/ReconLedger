"""crt.sh Certificate Transparency collector (PRD FR-08).

crt.sh has no formal API contract and is known to be slow or briefly
unavailable under load - hence the extended 60-second timeout (PRD 9/11) and
the rule that a crt.sh failure is always a typed provider warning, never a
job failure. Re-checked crt.sh's community-documented JSON query form
(?q=<value>&output=json) on 2026-09-06; there is still no official API
documentation and no authentication or rate limit.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.collectors.base import CachePolicy, CollectedFinding, CollectorContext, CollectorMetadata, RatePolicy
from app.collectors.caching import get_cached_findings, store_findings_in_cache
from app.collectors.errors import ProviderSchemaError
from app.models.enums import Category, TargetType
from app.security.gateway import parse_json_safely
from app.services.cache import CACHE_STATUS_EMPTY, CACHE_STATUS_SUCCESS, compute_cache_key
from app.services.fingerprint import compute_fingerprint

CRTSH_HOST = "crt.sh"
SCHEMA_VERSION = "1"
POSITIVE_TTL_SECONDS = 86400  # PRD FR-05: RDAP/RIPEstat/CT 24 hours
NEGATIVE_TTL_SECONDS = 3600
REQUEST_TIMEOUT_SECONDS = 60.0  # PRD 9/11: crt.sh defaults to 60 seconds, not the shared 30s default
MAX_RESPONSE_BYTES = 5_000_000

metadata = CollectorMetadata(
    name="crtsh",
    display_name="crt.sh (Certificate Transparency)",
    supported_targets=frozenset({TargetType.DOMAIN}),
    categories=frozenset({Category.NETWORK_FOOTPRINT}),
    required_credentials=(),
    provider_hosts=frozenset({CRTSH_HOST}),
    key_help_url="https://crt.sh/",
    rate_policy=RatePolicy(requests_per_period=2, period_seconds=1, burst=2, concurrency=1),
    cache_policy=CachePolicy(
        positive_ttl_seconds=POSITIVE_TTL_SECONDS, negative_ttl_seconds=NEGATIVE_TTL_SECONDS, schema_version=SCHEMA_VERSION
    ),
    request_timeout_seconds=REQUEST_TIMEOUT_SECONDS,
)


def _normalize_name(raw: str, target: str) -> tuple[str, bool] | None:
    name = raw.strip().rstrip(".").lower()
    if not name:
        return None
    is_wildcard = name.startswith("*.")
    if is_wildcard:
        name = name[2:]
        if not name:
            return None
    try:
        labels = [label.encode("idna").decode("ascii") for label in name.split(".")]
    except UnicodeError:
        return None
    canonical = ".".join(labels)
    if canonical != target and not canonical.endswith("." + target):
        return None
    return canonical, is_wildcard


async def run(context: CollectorContext) -> list[CollectedFinding]:
    target = context.target.normalized
    cache_key = compute_cache_key(collector="crtsh", schema_version=SCHEMA_VERSION, target_normalized=target)
    cached = await get_cached_findings(context, cache_key)
    if cached is not None:
        return cached

    url = httpx.URL(f"https://{CRTSH_HOST}/").copy_with(params={"q": target, "output": "json"})
    response = await context.gateway.get(
        url=str(url),
        allowed_hosts=frozenset({CRTSH_HOST}),
        timeout_seconds=REQUEST_TIMEOUT_SECONDS,
        max_response_bytes=MAX_RESPONSE_BYTES,
    )
    data = parse_json_safely(response, host=CRTSH_HOST)
    if not isinstance(data, list):
        raise ProviderSchemaError("crtsh", "response was not a JSON array")

    by_subdomain: dict[str, dict[str, Any]] = {}
    for cert in data:
        if not isinstance(cert, dict):
            continue
        cert_id = cert.get("id")
        name_value = cert.get("name_value") or ""
        for raw_name in str(name_value).split("\n"):
            parsed = _normalize_name(raw_name, target)
            if parsed is None:
                continue
            subdomain, is_wildcard = parsed
            entry = by_subdomain.setdefault(
                subdomain,
                {
                    "subdomain": subdomain,
                    "wildcard": False,
                    "cert_count": 0,
                    "cert_ids": [],
                    "issuers": set(),
                    "not_before_min": None,
                    "not_after_max": None,
                },
            )
            entry["wildcard"] = entry["wildcard"] or is_wildcard
            entry["cert_count"] += 1
            if cert_id is not None:
                entry["cert_ids"].append(cert_id)
            issuer = cert.get("issuer_name")
            if issuer:
                entry["issuers"].add(issuer)
            for bound_key, cert_key, reducer in (
                ("not_before_min", "not_before", min),
                ("not_after_max", "not_after", max),
            ):
                value = cert.get(cert_key)
                if value:
                    entry[bound_key] = value if entry[bound_key] is None else reducer(entry[bound_key], value)

    findings: list[CollectedFinding] = []
    for subdomain, entry in by_subdomain.items():
        entry["issuers"] = sorted(entry["issuers"])
        first_cert_id = entry["cert_ids"][0] if entry["cert_ids"] else None
        source_url = f"https://{CRTSH_HOST}/?id={first_cert_id}" if first_cert_id else f"https://{CRTSH_HOST}/?q={target}&output=json"
        wildcard_note = " (wildcard)" if entry["wildcard"] else ""
        findings.append(
            CollectedFinding(
                category=Category.NETWORK_FOOTPRINT,
                kind="ct.subdomain",
                title=f"{subdomain}{wildcard_note}",
                summary=f"Observed in {entry['cert_count']} certificate(s) issued by {', '.join(entry['issuers']) or 'unknown issuer'}",
                normalized_value=entry,
                raw_evidence={"cert_ids": entry["cert_ids"]},
                source_url=source_url,
                retrieved_at=datetime.now(timezone.utc),
                fingerprint=compute_fingerprint("crtsh", "ct.subdomain", {"target": target, "subdomain": subdomain}),
            )
        )

    status = CACHE_STATUS_SUCCESS if findings else CACHE_STATUS_EMPTY
    ttl = POSITIVE_TTL_SECONDS if findings else NEGATIVE_TTL_SECONDS
    await store_findings_in_cache(
        context.cache, cache_key, findings, status=status, response_json={"cert_count": len(data)}, ttl_seconds=ttl
    )
    return findings
