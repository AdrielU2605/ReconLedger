"""FR-12: the retention sweep deletes only terminal jobs older than the
retention window (and their dependent rows via cascade), plus expired
cache entries - never a queued/running job just because it's old, and
never a cache entry that hasn't expired yet."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.base import new_uuid, utcnow
from app.models.db import CacheEntry, CollectorRun, Finding, Job
from app.models.enums import Category, CollectorStatus, JobStatus, TargetType
from app.services.retention import sweep

PUBLIC_TEST_IP = "93.184.216.34"


async def _make_job(session_factory, *, status: JobStatus, finished_at) -> str:
    job_id = new_uuid()
    async with session_factory() as session:
        async with session.begin():
            session.add(
                Job(
                    id=job_id,
                    target_input=PUBLIC_TEST_IP,
                    target_normalized=PUBLIC_TEST_IP,
                    target_type=TargetType.IP,
                    status=status,
                    attestation_text="I own or am authorized to assess this target.",
                    attestation_version="1.0",
                    attestation_time=utcnow(),
                    selected_sources_json=["echo"],
                    finished_at=finished_at,
                )
            )
            session.add(CollectorRun(id=new_uuid(), job_id=job_id, collector="echo", status=CollectorStatus.DONE))
            session.add(
                Finding(
                    job_id=job_id, collector="echo", category=Category.NETWORK_FOOTPRINT, kind="echo.finding",
                    title="t", summary="s", normalized_value_json={}, raw_evidence_json={},
                    source_url="https://provider.example/e", retrieved_at=utcnow(), fingerprint=f"fp-{job_id}",
                )
            )
    return job_id


async def _job_exists(session_factory, job_id: str) -> bool:
    async with session_factory() as session:
        return await session.get(Job, job_id) is not None


@pytest.mark.asyncio
async def test_sweep_deletes_terminal_jobs_past_retention_and_cascades_findings(session_factory) -> None:
    old_job = await _make_job(session_factory, status=JobStatus.COMPLETED, finished_at=utcnow() - timedelta(days=100))
    await sweep(session_factory, retention_days=90)

    assert not await _job_exists(session_factory, old_job)
    async with session_factory() as session:
        findings = (await session.execute(select(Finding).where(Finding.job_id == old_job))).scalars().all()
    assert findings == []


@pytest.mark.asyncio
async def test_sweep_keeps_terminal_jobs_within_retention(session_factory) -> None:
    recent_job = await _make_job(session_factory, status=JobStatus.COMPLETED, finished_at=utcnow() - timedelta(days=1))
    await sweep(session_factory, retention_days=90)
    assert await _job_exists(session_factory, recent_job)


@pytest.mark.asyncio
async def test_sweep_never_deletes_a_running_job_regardless_of_age(session_factory) -> None:
    running_job = await _make_job(session_factory, status=JobStatus.RUNNING, finished_at=None)
    await sweep(session_factory, retention_days=0)
    assert await _job_exists(session_factory, running_job)


@pytest.mark.asyncio
async def test_sweep_removes_expired_cache_entries_and_keeps_fresh_ones(session_factory) -> None:
    now = utcnow()
    async with session_factory() as session:
        async with session.begin():
            session.add(
                CacheEntry(
                    cache_key="expired", collector="rdap", schema_version="1", status="success",
                    response_json={}, normalized_findings_json={}, retrieved_at=now, expires_at=now - timedelta(seconds=1),
                )
            )
            session.add(
                CacheEntry(
                    cache_key="fresh", collector="rdap", schema_version="1", status="success",
                    response_json={}, normalized_findings_json={}, retrieved_at=now, expires_at=now + timedelta(days=1),
                )
            )

    await sweep(session_factory, retention_days=90)

    async with session_factory() as session:
        remaining = (await session.execute(select(CacheEntry.cache_key))).scalars().all()
    assert remaining == ["fresh"]
