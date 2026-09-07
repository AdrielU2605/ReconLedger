"""Wayback Machine collector (PRD FR-09).

Two passes: (1) the CDX index gives historical URLs cheaply and in bulk -
this is the bulk of the evidence; (2) a small, byte-capped sample of actual
archived page content is fetched (via the "id_" raw-replay modifier, which
returns the captured bytes without Wayback's toolbar injection) to feed the
technology inference engine's archived-header/HTML signals. Redirects are
never followed for either pass (the default gateway behavior already
rejects them) - FR-09's "never follow a redirect to the live target" is
satisfied by simply never opting in to redirect-following at all here.

Re-checked the CDX Server API (github.com/internetarchive/wayback) and a
live query against example.com on 2026-09-07: output=json returns a header
row followed by data rows, standard fields urlkey/timestamp/original/
mimetype/statuscode/digest/length, in that order.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.collectors.archive_urls import canonicalize_archived_url, extract_extension, is_in_scope
from app.collectors.base import CachePolicy, CollectedFinding, CollectorContext, CollectorMetadata, RatePolicy
from app.collectors.caching import get_cached_findings, store_findings_in_cache
from app.collectors.errors import ProviderSchemaError
from app.models.enums import Category, TargetType
from app.security.errors import GatewayError
from app.security.gateway import parse_json_safely
from app.services.cache import CACHE_STATUS_EMPTY, CACHE_STATUS_SUCCESS, compute_cache_key
from app.services.fingerprint import compute_fingerprint

WAYBACK_HOST = "web.archive.org"
CDX_URL = f"https://{WAYBACK_HOST}/cdx/search/cdx"

SCHEMA_VERSION = "1"
POSITIVE_TTL_SECONDS = 43200  # PRD FR-05: Wayback 12 hours
NEGATIVE_TTL_SECONDS = 3600

MAX_INDEX_ROWS = 5000
MAX_REPRESENTATIVE_DOCS = 20
MAX_TOTAL_SAMPLE_BYTES = 5_000_000
PER_DOCUMENT_BYTE_CAP = 500_000

metadata = CollectorMetadata(
    name="wayback",
    display_name="Wayback Machine (Archived URLs)",
    supported_targets=frozenset({TargetType.DOMAIN}),
    categories=frozenset({Category.NETWORK_FOOTPRINT}),
    required_credentials=(),
    provider_hosts=frozenset({WAYBACK_HOST}),
    key_help_url="https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server",
    rate_policy=RatePolicy(requests_per_period=3, period_seconds=1, burst=3, concurrency=2),
    cache_policy=CachePolicy(
        positive_ttl_seconds=POSITIVE_TTL_SECONDS, negative_ttl_seconds=NEGATIVE_TTL_SECONDS, schema_version=SCHEMA_VERSION
    ),
)


def _parse_cdx_rows(data: Any) -> list[dict[str, str]]:
    if not isinstance(data, list) or not data:
        return []
    header, *rows = data
    if not isinstance(header, list) or "original" not in header or "timestamp" not in header:
        raise ProviderSchemaError("wayback", "CDX response missing its expected header row")
    return [dict(zip(header, row)) for row in rows if isinstance(row, list) and len(row) == len(header)]


def _aggregate_by_url(rows: list[dict[str, str]], target: str) -> dict[str, dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for row in rows:
        original = row.get("original")
        timestamp = row.get("timestamp")
        if not original or not timestamp:
            continue
        canonical = canonicalize_archived_url(original)
        if canonical is None or not is_in_scope(canonical, target):
            continue
        entry = by_url.setdefault(
            canonical,
            {"url": canonical, "first_seen": timestamp, "last_seen": timestamp, "mimetype": row.get("mimetype"),
             "statuscode": row.get("statuscode"), "extension": extract_extension(canonical),
             "best_timestamp": timestamp, "best_statuscode": row.get("statuscode")},
        )
        if timestamp < entry["first_seen"]:
            entry["first_seen"] = timestamp
        if timestamp > entry["last_seen"]:
            entry["last_seen"] = timestamp
            entry["mimetype"] = row.get("mimetype")
            entry["statuscode"] = row.get("statuscode")
        if row.get("statuscode") == "200":
            entry["best_timestamp"] = timestamp
            entry["best_statuscode"] = "200"
    return by_url


def _select_representative(by_url: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """A small, diverse sample for content fetching: prefer HTML, prefer
    variety of file extensions/paths over repeats of the same shape."""
    candidates = [e for e in by_url.values() if e["best_statuscode"] == "200"]
    candidates.sort(key=lambda e: (e["extension"] not in (None, "html", "htm"), e["url"]))
    seen_extensions: set[str | None] = set()
    selected: list[dict[str, Any]] = []
    for entry in candidates:
        if len(selected) >= MAX_REPRESENTATIVE_DOCS:
            break
        if entry["extension"] in seen_extensions and len(selected) < MAX_REPRESENTATIVE_DOCS // 2:
            continue  # prioritize diversity for the first half of the budget
        seen_extensions.add(entry["extension"])
        selected.append(entry)
    return selected[:MAX_REPRESENTATIVE_DOCS]


def _parse_raw_http_response(raw_bytes: bytes) -> tuple[dict[str, str], str]:
    text = raw_bytes.decode("utf-8", errors="replace")
    if "\r\n\r\n" not in text:
        return {}, text
    header_block, _, body = text.partition("\r\n\r\n")
    lines = header_block.split("\r\n")[1:]  # skip the status line
    headers = {}
    for line in lines:
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
    return headers, body


async def run(context: CollectorContext) -> list[CollectedFinding]:
    target = context.target.normalized
    cache_key = compute_cache_key(collector="wayback", schema_version=SCHEMA_VERSION, target_normalized=target)
    cached = await get_cached_findings(context, cache_key)
    if cached is not None:
        return cached

    url = httpx.URL(CDX_URL).copy_with(
        params={"url": target, "matchType": "domain", "output": "json", "limit": str(MAX_INDEX_ROWS), "collapse": "digest"}
    )
    response = await context.gateway.get(url=str(url), allowed_hosts=frozenset({WAYBACK_HOST}))
    data = parse_json_safely(response, host=WAYBACK_HOST)
    rows = _parse_cdx_rows(data)
    by_url = _aggregate_by_url(rows, target)

    findings: list[CollectedFinding] = []
    now = datetime.now(timezone.utc)
    for canonical, entry in by_url.items():
        findings.append(
            CollectedFinding(
                category=Category.NETWORK_FOOTPRINT,
                kind="wayback.url",
                title=canonical,
                summary=f"Archived {entry['first_seen']}–{entry['last_seen']} ({entry.get('mimetype') or 'unknown type'})",
                normalized_value={k: v for k, v in entry.items() if k != "best_timestamp" and k != "best_statuscode"},
                raw_evidence=entry,
                source_url=f"https://{WAYBACK_HOST}/web/{entry['last_seen']}/{canonical}",
                retrieved_at=now,
                fingerprint=compute_fingerprint("wayback", "wayback.url", {"url": canonical}),
            )
        )

    remaining_budget = MAX_TOTAL_SAMPLE_BYTES
    for entry in _select_representative(by_url):
        if remaining_budget <= 0:
            break
        replay_url = f"https://{WAYBACK_HOST}/web/{entry['best_timestamp']}id_/{entry['url']}"
        try:
            sample_response = await context.gateway.get(
                url=replay_url,
                allowed_hosts=frozenset({WAYBACK_HOST}),
                max_response_bytes=min(PER_DOCUMENT_BYTE_CAP, remaining_budget),
            )
        except GatewayError:
            continue  # a single sample failing is not worth failing the whole collector for
        if sample_response.status_code != 200:
            continue
        headers, body = _parse_raw_http_response(sample_response.content)
        remaining_budget -= len(sample_response.content)
        findings.append(
            CollectedFinding(
                category=Category.NETWORK_FOOTPRINT,
                kind="wayback.sample",
                title=f"Archived content sample: {entry['url']}",
                summary=f"Fetched a {len(body)}-byte archived snapshot from {entry['best_timestamp']}.",
                normalized_value={"url": entry["url"], "timestamp": entry["best_timestamp"], "headers": headers},
                raw_evidence={"headers": headers, "body_snippet": body[:20_000]},
                source_url=replay_url,
                retrieved_at=now,
                fingerprint=compute_fingerprint("wayback", "wayback.sample", {"url": entry["url"]}),
            )
        )

    status = CACHE_STATUS_SUCCESS if findings else CACHE_STATUS_EMPTY
    ttl = POSITIVE_TTL_SECONDS if findings else NEGATIVE_TTL_SECONDS
    await store_findings_in_cache(
        context.cache, cache_key, findings, status=status, response_json={"row_count": len(rows)}, ttl_seconds=ttl
    )
    return findings
