"""Common Crawl collector (PRD FR-09).

Common Crawl exposes many separate crawl collections rather than one index
(the collinfo.json bootstrap lists them); this collector queries a
configured number of the most recent ones (default 3) and records which
collection each finding came from. Its CDX index returns newline-delimited
JSON (one object per line) - a real difference from Wayback's single JSON
array that only showed up when this was checked against a live query, not
in any written spec. Content samples are fetched as HTTP byte-range
requests against the WARC segment named in each record's filename/offset/
length fields; each such range is an independently gzip-decompressable
member (confirmed against a live record on 2026-09-07), so no WARC library
is needed - decompress, then split on the blank-line boundaries between the
WARC header block, the HTTP response header block, and the body.

Re-checked index.commoncrawl.org's own documentation and live responses
(collinfo.json, a CDX query, and a byte-range content fetch) on 2026-09-07.
"""
from __future__ import annotations

import gzip
import json
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

INDEX_HOST = "index.commoncrawl.org"
DATA_HOST = "data.commoncrawl.org"
COLLINFO_URL = f"https://{INDEX_HOST}/collinfo.json"
ALLOWED_HOSTS = frozenset({INDEX_HOST, DATA_HOST})

SCHEMA_VERSION = "1"
POSITIVE_TTL_SECONDS = 604800  # PRD FR-05: Common Crawl 7 days
NEGATIVE_TTL_SECONDS = 3600
BOOTSTRAP_TTL_SECONDS = 604800

DEFAULT_COLLECTIONS_TO_QUERY = 3
MAX_INDEX_ROWS = 5000
MAX_REPRESENTATIVE_DOCS = 20
MAX_TOTAL_SAMPLE_BYTES = 5_000_000
PER_DOCUMENT_BYTE_CAP = 500_000

metadata = CollectorMetadata(
    name="commoncrawl",
    display_name="Common Crawl",
    supported_targets=frozenset({TargetType.DOMAIN}),
    categories=frozenset({Category.NETWORK_FOOTPRINT}),
    required_credentials=(),
    provider_hosts=ALLOWED_HOSTS,
    key_help_url="https://index.commoncrawl.org/",
    rate_policy=RatePolicy(requests_per_period=3, period_seconds=1, burst=3, concurrency=2),
    cache_policy=CachePolicy(
        positive_ttl_seconds=POSITIVE_TTL_SECONDS, negative_ttl_seconds=NEGATIVE_TTL_SECONDS, schema_version=SCHEMA_VERSION
    ),
)


async def _fetch_recent_collection_apis(context: CollectorContext) -> list[tuple[str, str]]:
    """Returns [(collection_id, cdx_api_url), ...] for the N most recent collections."""
    cache_key = compute_cache_key(collector="commoncrawl", schema_version=SCHEMA_VERSION, target_normalized="collinfo", variant="bootstrap")
    cached = await context.cache.get(cache_key)
    if cached is not None:
        collections = cached.response_json.get("collections", [])
    else:
        response = await context.gateway.get(url=COLLINFO_URL, allowed_hosts=ALLOWED_HOSTS)
        data = parse_json_safely(response, host=INDEX_HOST)
        if not isinstance(data, list):
            raise ProviderSchemaError("commoncrawl", "collinfo.json was not a JSON array")
        collections = [
            {"id": entry.get("id"), "cdx_api": entry.get("cdx-api")}
            for entry in data
            if isinstance(entry, dict) and entry.get("id") and entry.get("cdx-api")
        ]
        await context.cache.set(
            cache_key, status=CACHE_STATUS_SUCCESS, response_json={"collections": collections},
            normalized_findings_json={}, ttl_seconds=BOOTSTRAP_TTL_SECONDS,
        )
    return [(c["id"], c["cdx_api"]) for c in collections[:DEFAULT_COLLECTIONS_TO_QUERY]]


def _parse_ndjson_rows(raw_text: str) -> list[dict[str, Any]]:
    rows = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue  # one malformed line should not discard the rest of the index
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _aggregate_by_url(rows: list[tuple[str, dict[str, Any]]], target: str) -> dict[str, dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for collection_id, row in rows:
        original = row.get("url")
        timestamp = row.get("timestamp")
        if not original or not timestamp:
            continue
        canonical = canonicalize_archived_url(original)
        if canonical is None or not is_in_scope(canonical, target):
            continue
        entry = by_url.setdefault(
            canonical,
            {"url": canonical, "collections": set(), "first_seen": timestamp, "last_seen": timestamp,
             "mime": row.get("mime"), "status": row.get("status"), "extension": extract_extension(canonical),
             "best_record": None},
        )
        entry["collections"].add(collection_id)
        if timestamp < entry["first_seen"]:
            entry["first_seen"] = timestamp
        if timestamp > entry["last_seen"]:
            entry["last_seen"] = timestamp
            entry["mime"] = row.get("mime")
            entry["status"] = row.get("status")
        if row.get("status") == "200" and row.get("filename") and entry["best_record"] is None:
            entry["best_record"] = row
    return by_url


def _select_representative(by_url: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [e for e in by_url.values() if e["best_record"] is not None]
    candidates.sort(key=lambda e: (e["extension"] not in (None, "html", "htm"), e["url"]))
    seen_extensions: set[str | None] = set()
    selected: list[dict[str, Any]] = []
    for entry in candidates:
        if len(selected) >= MAX_REPRESENTATIVE_DOCS:
            break
        if entry["extension"] in seen_extensions and len(selected) < MAX_REPRESENTATIVE_DOCS // 2:
            continue
        seen_extensions.add(entry["extension"])
        selected.append(entry)
    return selected[:MAX_REPRESENTATIVE_DOCS]


def _parse_warc_record(raw_gzip_bytes: bytes) -> tuple[dict[str, str], str] | None:
    try:
        decompressed = gzip.decompress(raw_gzip_bytes)
    except (OSError, EOFError):
        return None
    text = decompressed.decode("utf-8", errors="replace")
    # WARC header block, blank line, HTTP status+header block, blank line, body.
    parts = text.split("\r\n\r\n", 2)
    if len(parts) < 3:
        return None
    _warc_headers, http_header_block, body = parts
    headers = {}
    for line in http_header_block.split("\r\n")[1:]:  # skip the HTTP status line
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
    return headers, body


async def run(context: CollectorContext) -> list[CollectedFinding]:
    target = context.target.normalized
    cache_key = compute_cache_key(collector="commoncrawl", schema_version=SCHEMA_VERSION, target_normalized=target)
    cached = await get_cached_findings(context, cache_key)
    if cached is not None:
        return cached

    collections = await _fetch_recent_collection_apis(context)
    if not collections:
        raise ProviderSchemaError("commoncrawl", "collinfo.json returned no usable collections")

    per_collection_limit = max(1, MAX_INDEX_ROWS // len(collections))
    all_rows: list[tuple[str, dict[str, Any]]] = []
    for collection_id, cdx_api in collections:
        url = httpx.URL(cdx_api).copy_with(params={"url": target, "matchType": "domain", "output": "json", "limit": str(per_collection_limit)})
        try:
            response = await context.gateway.get(url=str(url), allowed_hosts=ALLOWED_HOSTS)
        except GatewayError:
            continue  # this collection being unavailable should not fail the others
        if response.status_code == 404:
            continue  # no captures for this domain in this collection
        rows = _parse_ndjson_rows(response.text)
        all_rows.extend((collection_id, row) for row in rows)

    by_url = _aggregate_by_url(all_rows, target)

    findings: list[CollectedFinding] = []
    now = datetime.now(timezone.utc)
    for canonical, entry in by_url.items():
        collections_list = sorted(entry["collections"])
        findings.append(
            CollectedFinding(
                category=Category.NETWORK_FOOTPRINT,
                kind="commoncrawl.url",
                title=canonical,
                summary=f"Indexed in {', '.join(collections_list)} ({entry.get('mime') or 'unknown type'})",
                normalized_value={
                    "url": canonical, "collections": collections_list, "first_seen": entry["first_seen"],
                    "last_seen": entry["last_seen"], "mime": entry.get("mime"), "status": entry.get("status"),
                    "extension": entry["extension"],
                },
                raw_evidence={
                    "url": canonical, "collections": collections_list, "first_seen": entry["first_seen"],
                    "last_seen": entry["last_seen"], "mime": entry.get("mime"), "status": entry.get("status"),
                },
                source_url=f"https://{INDEX_HOST}/{collections_list[-1]}-index?url={canonical}&output=json",
                retrieved_at=now,
                fingerprint=compute_fingerprint("commoncrawl", "commoncrawl.url", {"url": canonical}),
            )
        )

    remaining_budget = MAX_TOTAL_SAMPLE_BYTES
    for entry in _select_representative(by_url):
        if remaining_budget <= 0:
            break
        record = entry["best_record"]
        try:
            length = int(record["length"])
            offset = int(record["offset"])
        except (KeyError, ValueError):
            continue
        if length > min(PER_DOCUMENT_BYTE_CAP, remaining_budget):
            continue
        data_url = f"https://{DATA_HOST}/{record['filename']}"
        try:
            sample_response = await context.gateway.get(
                url=data_url,
                allowed_hosts=ALLOWED_HOSTS,
                headers={"Range": f"bytes={offset}-{offset + length - 1}"},
                max_response_bytes=length + 1024,
            )
        except GatewayError:
            continue
        if sample_response.status_code not in (200, 206):
            continue
        parsed = _parse_warc_record(sample_response.content)
        if parsed is None:
            continue
        headers, body = parsed
        remaining_budget -= len(sample_response.content)
        findings.append(
            CollectedFinding(
                category=Category.NETWORK_FOOTPRINT,
                kind="commoncrawl.sample",
                title=f"Archived content sample: {entry['url']}",
                summary=f"Fetched a {len(body)}-byte archived snapshot from {sorted(entry['collections'])[-1]}.",
                normalized_value={"url": entry["url"], "collection": sorted(entry["collections"])[-1], "headers": headers},
                raw_evidence={"headers": headers, "body_snippet": body[:20_000]},
                source_url=data_url,
                retrieved_at=now,
                fingerprint=compute_fingerprint("commoncrawl", "commoncrawl.sample", {"url": entry["url"]}),
            )
        )

    status = CACHE_STATUS_SUCCESS if findings else CACHE_STATUS_EMPTY
    ttl = POSITIVE_TTL_SECONDS if findings else NEGATIVE_TTL_SECONDS
    await store_findings_in_cache(
        context.cache, cache_key, findings, status=status,
        response_json={"row_count": len(all_rows), "collections": [c for c, _ in collections]}, ttl_seconds=ttl,
    )
    return findings
