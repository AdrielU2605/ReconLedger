"""Technology inference: evidence-backed rules over sibling collectors'
already-persisted findings. Never touches the gateway (FR-10: no inference
rule triggers a live verification request)."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.collectors import technology
from app.db.base import utcnow
from app.models.db import Finding, Job
from app.models.enums import Category, JobStatus, TargetType
from tests.integration._collector_helpers import make_context, make_gateway


def _never_called_gateway():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("technology inference must never call the gateway")

    return make_gateway(handler, {})


async def _make_job(session_factory) -> str:
    async with session_factory() as session:
        async with session.begin():
            job = Job(
                target_input="example.com", target_normalized="example.com", target_type=TargetType.DOMAIN,
                status=JobStatus.RUNNING, attestation_text="...", attestation_version="1",
                attestation_time=utcnow(), selected_sources_json=["technology"], created_at=utcnow(),
            )
            session.add(job)
        await session.refresh(job)
        return job.id


async def _seed_finding(session_factory, job_id: str, **overrides) -> None:
    defaults = dict(
        job_id=job_id,
        collector="dns_doh",
        category=Category.NETWORK_FOOTPRINT,
        kind="dns.ns",
        title="x",
        summary="x",
        normalized_value_json={},
        raw_evidence_json={},
        source_url="https://dns.google/",
        retrieved_at=datetime.now(timezone.utc),
        fingerprint="fp-1",
    )
    defaults.update(overrides)
    async with session_factory() as session:
        async with session.begin():
            session.add(Finding(**defaults))


@pytest.mark.asyncio
async def test_no_evidence_produces_no_findings(session_factory) -> None:
    context = make_context(session_factory, _never_called_gateway(), target_type=TargetType.DOMAIN, target_normalized="example.com", collector="technology")
    assert await technology.run(context) == []


@pytest.mark.asyncio
async def test_cloudflare_nameserver_is_detected(session_factory) -> None:
    job_id = await _make_job(session_factory)
    await _seed_finding(
        session_factory, job_id, kind="dns.ns", fingerprint="fp-ns",
        normalized_value_json={"nameservers": ["ns1.cloudflare.com", "ns2.cloudflare.com"]},
    )
    context = make_context(session_factory, _never_called_gateway(), target_type=TargetType.DOMAIN, target_normalized="example.com", collector="technology", job_id=job_id)

    findings = await technology.run(context)
    assert len(findings) == 1
    assert findings[0].title == "Cloudflare (DNS/CDN)"
    assert findings[0].category == Category.TECHNOLOGY_STACK


@pytest.mark.asyncio
async def test_google_workspace_mx_is_detected(session_factory) -> None:
    job_id = await _make_job(session_factory)
    await _seed_finding(
        session_factory, job_id, kind="dns.mx", fingerprint="fp-mx",
        normalized_value_json={"records": [{"preference": 1, "exchange": "aspmx.l.google.com"}]},
    )
    context = make_context(session_factory, _never_called_gateway(), target_type=TargetType.DOMAIN, target_normalized="example.com", collector="technology", job_id=job_id)

    findings = await technology.run(context)
    assert any(f.title == "Google Workspace (Gmail)" for f in findings)


@pytest.mark.asyncio
async def test_wordpress_detected_from_archived_html_path(session_factory) -> None:
    job_id = await _make_job(session_factory)
    await _seed_finding(
        session_factory, job_id, kind="wayback.sample", fingerprint="fp-sample", collector="wayback",
        normalized_value_json={"headers": {}},
        raw_evidence_json={"body_snippet": '<html><script src="/wp-content/themes/x/script.js"></script></html>'},
    )
    context = make_context(session_factory, _never_called_gateway(), target_type=TargetType.DOMAIN, target_normalized="example.com", collector="technology", job_id=job_id)

    findings = await technology.run(context)
    assert any(f.title == "WordPress" for f in findings)


@pytest.mark.asyncio
async def test_server_header_detected_from_commoncrawl_sample(session_factory) -> None:
    job_id = await _make_job(session_factory)
    await _seed_finding(
        session_factory, job_id, kind="commoncrawl.sample", fingerprint="fp-cc-sample", collector="commoncrawl",
        normalized_value_json={"headers": {"server": "nginx/1.24"}},
        raw_evidence_json={"body_snippet": ""},
    )
    context = make_context(session_factory, _never_called_gateway(), target_type=TargetType.DOMAIN, target_normalized="example.com", collector="technology", job_id=job_id)

    findings = await technology.run(context)
    assert any(f.title == "nginx" and f.confidence.value == "low" for f in findings)


@pytest.mark.asyncio
async def test_same_technology_from_two_samples_merges_into_one_finding_with_both_supporting_ids(session_factory) -> None:
    job_id = await _make_job(session_factory)
    await _seed_finding(
        session_factory, job_id, kind="wayback.sample", fingerprint="fp-a", collector="wayback",
        normalized_value_json={"headers": {"server": "cloudflare"}}, raw_evidence_json={"body_snippet": ""},
    )
    await _seed_finding(
        session_factory, job_id, kind="commoncrawl.sample", fingerprint="fp-b", collector="commoncrawl",
        normalized_value_json={"headers": {"server": "cloudflare"}}, raw_evidence_json={"body_snippet": ""},
    )
    context = make_context(session_factory, _never_called_gateway(), target_type=TargetType.DOMAIN, target_normalized="example.com", collector="technology", job_id=job_id)

    findings = await technology.run(context)
    cloudflare = [f for f in findings if f.title == "Cloudflare"]
    assert len(cloudflare) == 1
    assert len(cloudflare[0].normalized_value["supporting_finding_ids"]) == 2


@pytest.mark.asyncio
async def test_generator_meta_tag_is_detected(session_factory) -> None:
    job_id = await _make_job(session_factory)
    await _seed_finding(
        session_factory, job_id, kind="wayback.sample", fingerprint="fp-gen", collector="wayback",
        normalized_value_json={"headers": {}},
        raw_evidence_json={"body_snippet": '<meta name="generator" content="WordPress 6.4" />'},
    )
    context = make_context(session_factory, _never_called_gateway(), target_type=TargetType.DOMAIN, target_normalized="example.com", collector="technology", job_id=job_id)

    findings = await technology.run(context)
    assert any(f.title == "WordPress" and "generator" in f.summary.lower() for f in findings)


@pytest.mark.asyncio
async def test_unrelated_finding_kinds_are_ignored(session_factory) -> None:
    job_id = await _make_job(session_factory)
    await _seed_finding(session_factory, job_id, kind="rdap.registration", collector="rdap", fingerprint="fp-rdap")
    context = make_context(session_factory, _never_called_gateway(), target_type=TargetType.DOMAIN, target_normalized="example.com", collector="technology", job_id=job_id)

    assert await technology.run(context) == []
