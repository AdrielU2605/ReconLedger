"""Wayback collector: CDX parsing, scope filtering/dedup, content sampling,
and the "never follow a redirect" rule for both passes."""
from __future__ import annotations

import httpx
import pytest

from app.collectors import wayback
from app.collectors.errors import ProviderSchemaError
from app.models.enums import TargetType
from tests.integration._collector_helpers import make_context, make_gateway

CDX_HEADER = ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"]

CDX_ROWS = [
    ["com,example)/", "20200101000000", "http://example.com/", "text/html", "200", "DIGESTA", "100"],
    ["com,example)/", "20210101000000", "https://example.com/", "text/html", "200", "DIGESTB", "120"],
    ["com,example)/about", "20200601000000", "https://example.com/about#section", "text/html", "200", "DIGESTC", "90"],
    ["com,example)/about", "20220301000000", "https://example.com/about", "text/html", "200", "DIGESTE", "95"],
    ["com,not-example)/", "20200101000000", "https://not-example.com/", "text/html", "200", "DIGESTD", "80"],
]


def _index_handler(rows=CDX_ROWS, sample_handler=None):
    async def handler(request: httpx.Request) -> httpx.Response:
        if "id_" in request.url.path:
            if sample_handler:
                return await sample_handler(request)
            return httpx.Response(404)
        return httpx.Response(200, json=[CDX_HEADER, *rows])

    return handler


@pytest.mark.asyncio
async def test_urls_are_deduplicated_by_canonical_form_and_scoped_to_target(session_factory) -> None:
    """Scheme is part of the canonical form (FR-09 says dedupe "by canonical
    URL", not "ignoring scheme") - http and https captures of the same path
    are distinct rows; the fragment is stripped and the out-of-scope host
    is dropped entirely."""
    gateway = make_gateway(_index_handler(), {"web.archive.org": "8.8.8.8"})
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="wayback")

    findings = await wayback.run(context)
    url_findings = [f for f in findings if f.kind == "wayback.url"]

    urls = {f.normalized_value["url"] for f in url_findings}
    assert urls == {"http://example.com/", "https://example.com/", "https://example.com/about"}


@pytest.mark.asyncio
async def test_first_and_last_seen_span_the_full_observed_range(session_factory) -> None:
    gateway = make_gateway(_index_handler(), {"web.archive.org": "8.8.8.8"})
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="wayback")

    findings = await wayback.run(context)
    about = next(f for f in findings if f.kind == "wayback.url" and f.normalized_value["url"] == "https://example.com/about")
    assert about.normalized_value["first_seen"] == "20200601000000"
    assert about.normalized_value["last_seen"] == "20220301000000"


@pytest.mark.asyncio
async def test_missing_header_row_is_a_schema_error(session_factory) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[["not", "a", "row"]])

    gateway = make_gateway(handler, {"web.archive.org": "8.8.8.8"})
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="wayback")

    with pytest.raises(ProviderSchemaError):
        await wayback.run(context)


@pytest.mark.asyncio
async def test_empty_index_produces_no_findings(session_factory) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    gateway = make_gateway(handler, {"web.archive.org": "8.8.8.8"})
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="wayback")

    assert await wayback.run(context) == []


@pytest.mark.asyncio
async def test_content_sample_is_fetched_and_parsed_into_headers_and_body(session_factory) -> None:
    async def sample_handler(request: httpx.Request) -> httpx.Response:
        raw = b"HTTP/1.1 200 OK\r\nServer: nginx\r\nContent-Type: text/html\r\n\r\n<html>hi</html>"
        return httpx.Response(200, content=raw)

    gateway = make_gateway(_index_handler(sample_handler=sample_handler), {"web.archive.org": "8.8.8.8"})
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="wayback")

    findings = await wayback.run(context)
    samples = [f for f in findings if f.kind == "wayback.sample"]
    assert len(samples) >= 1
    assert samples[0].normalized_value["headers"]["server"] == "nginx"
    assert "<html>hi</html>" in samples[0].raw_evidence["body_snippet"]


@pytest.mark.asyncio
async def test_a_redirect_during_content_sampling_is_skipped_not_fatal(session_factory) -> None:
    """The gateway rejects the redirect (no allow_redirect_to is passed for
    sample fetches - FR-09's "never follow to the live target" is satisfied
    by simply never opting in); one sample failing must not fail the job."""

    async def sample_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://example.com/live"})

    gateway = make_gateway(_index_handler(sample_handler=sample_handler), {"web.archive.org": "8.8.8.8"})
    context = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="wayback")

    findings = await wayback.run(context)
    assert any(f.kind == "wayback.url" for f in findings)
    assert not any(f.kind == "wayback.sample" for f in findings)


@pytest.mark.asyncio
async def test_repeat_run_is_served_from_cache(session_factory) -> None:
    call_count = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if "id_" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, json=[CDX_HEADER, *CDX_ROWS])

    gateway = make_gateway(handler, {"web.archive.org": "8.8.8.8"})
    context1 = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="wayback")
    await wayback.run(context1)
    calls_after_first = call_count["n"]

    context2 = make_context(session_factory, gateway, target_type=TargetType.DOMAIN, target_normalized="example.com", collector="wayback")
    await wayback.run(context2)

    assert call_count["n"] == calls_after_first
    assert context2.cache_hit is True
