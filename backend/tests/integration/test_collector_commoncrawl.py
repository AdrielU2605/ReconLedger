"""Common Crawl collector: collinfo bootstrap caching, NDJSON parsing
(including a malformed line), multi-collection aggregation, and WARC
byte-range content sampling."""
from __future__ import annotations

import gzip
import json

import httpx
import pytest

from app.collectors import commoncrawl
from app.models.enums import TargetType
from tests.integration._collector_helpers import make_context, make_gateway

COLLINFO = [
    {"id": "CC-MAIN-2026-34", "cdx-api": "https://index.commoncrawl.org/CC-MAIN-2026-34-index"},
    {"id": "CC-MAIN-2026-30", "cdx-api": "https://index.commoncrawl.org/CC-MAIN-2026-30-index"},
]


def _ndjson(*records: dict) -> str:
    return "\n".join(json.dumps(r) for r in records)


def _warc_gzip(headers: dict[str, str], body: str) -> bytes:
    header_lines = "\r\n".join(f"{k}: {v}" for k, v in headers.items())
    raw = f"WARC/1.0\r\nWARC-Type: response\r\n\r\nHTTP/1.1 200 OK\r\n{header_lines}\r\n\r\n{body}".encode()
    return gzip.compress(raw)


def _handler_for(collections: dict[str, str], sample_bytes: bytes | None = None):
    """collections maps collection-id -> ndjson body for that collection's index."""

    async def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers.get("host")
        if host == "index.commoncrawl.org" and request.url.path == "/collinfo.json":
            return httpx.Response(200, json=COLLINFO)
        if host == "index.commoncrawl.org":
            for coll_id, body in collections.items():
                if coll_id in request.url.path:
                    return httpx.Response(200, text=body)
            return httpx.Response(404)
        if host == "data.commoncrawl.org":
            if sample_bytes is None:
                return httpx.Response(404)
            return httpx.Response(206, content=sample_bytes)
        raise AssertionError(f"unexpected request to {host}{request.url.path}")

    return handler


def _record(url: str, timestamp: str, **overrides) -> dict:
    base = {
        "url": url, "timestamp": timestamp, "mime": "text/html", "status": "200",
        "filename": "crawl-data/x.warc.gz", "offset": "0", "length": str(overrides.pop("length", 100)),
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_urls_are_scoped_and_deduplicated_across_collections(session_factory) -> None:
    collections = {
        "CC-MAIN-2026-34": _ndjson(_record("https://example.com/", "20260807000000")),
        "CC-MAIN-2026-30": _ndjson(
            _record("https://example.com/", "20260710000000"),
            _record("https://not-example.com/", "20260710000000"),
        ),
    }
    gateway = make_gateway(_handler_for(collections), {"index.commoncrawl.org": "8.8.8.8", "data.commoncrawl.org": "8.8.4.4"})
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="commoncrawl")

    findings = await commoncrawl.run(context)
    url_findings = [f for f in findings if f.kind == "commoncrawl.url"]

    assert len(url_findings) == 1  # not-example.com dropped, example.com merged across 2 collections
    assert set(url_findings[0].normalized_value["collections"]) == {"CC-MAIN-2026-34", "CC-MAIN-2026-30"}


@pytest.mark.asyncio
async def test_malformed_ndjson_line_is_skipped_not_fatal(session_factory) -> None:
    body = _ndjson(_record("https://example.com/", "20260807000000")) + "\nnot valid json\n"
    collections = {"CC-MAIN-2026-34": body, "CC-MAIN-2026-30": ""}
    gateway = make_gateway(_handler_for(collections), {"index.commoncrawl.org": "8.8.8.8", "data.commoncrawl.org": "8.8.4.4"})
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="commoncrawl")

    findings = await commoncrawl.run(context)
    assert any(f.kind == "commoncrawl.url" for f in findings)


@pytest.mark.asyncio
async def test_content_sample_is_fetched_via_byte_range_and_warc_parsed(session_factory) -> None:
    sample = _warc_gzip({"Server": "nginx", "Content-Type": "text/html"}, "<html>hi</html>")
    collections = {
        "CC-MAIN-2026-34": _ndjson(_record("https://example.com/", "20260807000000", length=len(sample))),
        "CC-MAIN-2026-30": "",
    }

    range_headers_seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("host") == "data.commoncrawl.org":
            range_headers_seen.append(request.headers.get("range"))
            return httpx.Response(206, content=sample)
        return await _handler_for(collections)(request)

    gateway = make_gateway(handler, {"index.commoncrawl.org": "8.8.8.8", "data.commoncrawl.org": "8.8.4.4"})
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="commoncrawl")

    findings = await commoncrawl.run(context)
    samples = [f for f in findings if f.kind == "commoncrawl.sample"]

    assert len(samples) == 1
    assert samples[0].normalized_value["headers"]["server"] == "nginx"
    assert "<html>hi</html>" in samples[0].raw_evidence["body_snippet"]
    assert range_headers_seen == ["bytes=0-" + str(len(sample) - 1)]


@pytest.mark.asyncio
async def test_corrupt_gzip_sample_is_skipped_not_fatal(session_factory) -> None:
    collections = {
        "CC-MAIN-2026-34": _ndjson(_record("https://example.com/", "20260807000000", length=10)),
        "CC-MAIN-2026-30": "",
    }
    gateway = make_gateway(_handler_for(collections, sample_bytes=b"not actually gzip"), {"index.commoncrawl.org": "8.8.8.8", "data.commoncrawl.org": "8.8.4.4"})
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="commoncrawl")

    findings = await commoncrawl.run(context)
    assert any(f.kind == "commoncrawl.url" for f in findings)
    assert not any(f.kind == "commoncrawl.sample" for f in findings)


@pytest.mark.asyncio
async def test_repeat_run_is_served_from_cache(session_factory) -> None:
    call_count = {"n": 0}
    collections = {"CC-MAIN-2026-34": _ndjson(_record("https://example.com/", "20260807000000")), "CC-MAIN-2026-30": ""}
    base_handler = _handler_for(collections)

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return await base_handler(request)

    gateway = make_gateway(handler, {"index.commoncrawl.org": "8.8.8.8", "data.commoncrawl.org": "8.8.4.4"})
    context1 = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="commoncrawl")
    await commoncrawl.run(context1)
    calls_after_first = call_count["n"]

    context2 = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="commoncrawl")
    await commoncrawl.run(context2)

    assert call_count["n"] == calls_after_first
    assert context2.cache_hit is True
