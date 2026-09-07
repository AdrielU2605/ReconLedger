"""Exercises the job runner end to end against a real (migrated, temp-file)
SQLite database, using fake collectors instead of real providers. This is
what proves claim/dispatch/progress/cancel/restart-recovery/concurrency
actually work together, not just in isolated unit tests.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app.collectors.base import (
    CachePolicy,
    CollectedFinding,
    CollectorContext,
    CollectorMetadata,
    RatePolicy,
)
from app.collectors.errors import CredentialMissingError
from app.collectors.registry import CollectorRegistry
from app.config import Settings
from app.db.base import new_uuid, utcnow
from app.jobs.runner import JobRunner
from app.models.db import CollectorRun, Finding, Job
from app.models.enums import Category, CollectorStatus, JobStatus, TargetType
from app.security.gateway import OutboundGateway
from app.security.network import StaticResolver

PUBLIC_TEST_IP = "93.184.216.34"


def _never_called_transport() -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no provider request was expected, got {request.url}")

    return httpx.MockTransport(handler)


def _fake_gateway_factory(settings: Settings) -> OutboundGateway:
    return OutboundGateway(transport=_never_called_transport(), resolver=StaticResolver(table={}), settings=settings)


class ScriptedCollector:
    """A test-only collector whose behavior is scripted per test."""

    def __init__(self, name: str, *, supported=frozenset({TargetType.IP, TargetType.DOMAIN})) -> None:
        self.metadata = CollectorMetadata(
            name=name,
            display_name=name,
            supported_targets=frozenset(supported),
            categories=frozenset({Category.NETWORK_FOOTPRINT}),
            required_credentials=(),
            provider_hosts=frozenset(),
            key_help_url=None,
            rate_policy=RatePolicy(requests_per_period=1, period_seconds=1, burst=1, concurrency=1),
            cache_policy=CachePolicy(positive_ttl_seconds=1, negative_ttl_seconds=1, schema_version="1"),
            test_only=True,
        )
        self.calls = 0
        self.on_run = None  # set by the test

    async def run(self, context: CollectorContext) -> list[CollectedFinding]:
        self.calls += 1
        if self.on_run is not None:
            return await self.on_run(context)
        return []


def _finding(kind: str = "test.finding") -> CollectedFinding:
    return CollectedFinding(
        category=Category.NETWORK_FOOTPRINT,
        kind=kind,
        title="A finding",
        summary="A summary",
        normalized_value={},
        raw_evidence={},
        source_url="https://provider.example/evidence",
        retrieved_at=datetime.now(timezone.utc),
        fingerprint=f"fp-{kind}",
    )


async def _create_job(session_factory, *, target_type: TargetType, target_normalized: str, collector_names: list[str], status: JobStatus = JobStatus.QUEUED) -> str:
    job_id = new_uuid()
    async with session_factory() as session:
        async with session.begin():
            session.add(
                Job(
                    id=job_id,
                    target_input=target_normalized,
                    target_normalized=target_normalized,
                    target_type=target_type,
                    status=status,
                    attestation_text="I own or am authorized to assess this target.",
                    attestation_version="1.0",
                    attestation_time=utcnow(),
                    selected_sources_json=collector_names,
                    started_at=utcnow() if status != JobStatus.QUEUED else None,
                )
            )
            for name in collector_names:
                session.add(CollectorRun(id=new_uuid(), job_id=job_id, collector=name, status=CollectorStatus.QUEUED))
    return job_id


async def _get_job(session_factory, job_id: str) -> Job:
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        return job


async def _get_collector_runs(session_factory, job_id: str) -> list[CollectorRun]:
    async with session_factory() as session:
        from sqlalchemy import select

        result = await session.execute(select(CollectorRun).where(CollectorRun.job_id == job_id))
        return list(result.scalars().all())


def _make_runner(session_factory, registry: CollectorRegistry, **settings_overrides) -> JobRunner:
    settings = Settings(_env_file=None, **settings_overrides)
    return JobRunner(session_factory=session_factory, registry=registry, settings=settings, gateway_factory=_fake_gateway_factory)


@pytest.mark.asyncio
async def test_claim_next_queued_job_claims_oldest_first(session_factory) -> None:
    older = await _create_job(session_factory, target_type=TargetType.IP, target_normalized=PUBLIC_TEST_IP, collector_names=[])
    await asyncio.sleep(0.01)
    await _create_job(session_factory, target_type=TargetType.IP, target_normalized=PUBLIC_TEST_IP, collector_names=[])

    runner = _make_runner(session_factory, CollectorRegistry())
    claimed = await runner.claim_next_queued_job()

    assert claimed == older
    job = await _get_job(session_factory, older)
    assert job.status == JobStatus.RUNNING
    assert job.started_at is not None


@pytest.mark.asyncio
async def test_claim_returns_none_when_nothing_queued(session_factory) -> None:
    runner = _make_runner(session_factory, CollectorRegistry())
    assert await runner.claim_next_queued_job() is None


@pytest.mark.asyncio
async def test_successful_collector_persists_finding_and_completes_job(session_factory) -> None:
    collector = ScriptedCollector("succeeds")
    collector.on_run = lambda ctx: asyncio.sleep(0, result=[_finding()])
    registry = CollectorRegistry()
    registry.register(collector, allow_test_only=True)

    job_id = await _create_job(session_factory, target_type=TargetType.IP, target_normalized=PUBLIC_TEST_IP, collector_names=["succeeds"], status=JobStatus.RUNNING)
    runner = _make_runner(session_factory, registry)
    await runner.run_job(job_id)

    job = await _get_job(session_factory, job_id)
    assert job.status == JobStatus.COMPLETED
    assert job.finished_at is not None

    runs = await _get_collector_runs(session_factory, job_id)
    assert runs[0].status == CollectorStatus.DONE
    assert runs[0].finding_count == 1

    async with session_factory() as session:
        from sqlalchemy import select

        findings = (await session.execute(select(Finding).where(Finding.job_id == job_id))).scalars().all()
    assert len(findings) == 1
    assert findings[0].fingerprint == "fp-test.finding"


@pytest.mark.asyncio
async def test_mixed_success_and_failure_is_completed_with_warnings(session_factory) -> None:
    good = ScriptedCollector("good")
    good.on_run = lambda ctx: asyncio.sleep(0, result=[_finding()])
    bad = ScriptedCollector("bad")

    async def _fail(ctx):
        raise CredentialMissingError("bad", "api_key")

    bad.on_run = _fail

    registry = CollectorRegistry()
    registry.register(good, allow_test_only=True)
    registry.register(bad, allow_test_only=True)

    job_id = await _create_job(session_factory, target_type=TargetType.IP, target_normalized=PUBLIC_TEST_IP, collector_names=["good", "bad"], status=JobStatus.RUNNING)
    runner = _make_runner(session_factory, registry)
    await runner.run_job(job_id)

    job = await _get_job(session_factory, job_id)
    # skipped_no_key is a valid terminal state, not a failure - COMPLETED, not warnings.
    assert job.status == JobStatus.COMPLETED
    runs = {r.collector: r for r in await _get_collector_runs(session_factory, job_id)}
    assert runs["good"].status == CollectorStatus.DONE
    assert runs["bad"].status == CollectorStatus.SKIPPED_NO_KEY
    assert runs["bad"].safe_error_code == "skipped_no_key"


@pytest.mark.asyncio
async def test_actual_failure_alongside_success_is_completed_with_warnings(session_factory) -> None:
    good = ScriptedCollector("good")
    good.on_run = lambda ctx: asyncio.sleep(0, result=[_finding()])
    broken = ScriptedCollector("broken")

    async def _raise_unexpected(ctx):
        raise RuntimeError("boom")

    broken.on_run = _raise_unexpected

    registry = CollectorRegistry()
    registry.register(good, allow_test_only=True)
    registry.register(broken, allow_test_only=True)

    job_id = await _create_job(session_factory, target_type=TargetType.IP, target_normalized=PUBLIC_TEST_IP, collector_names=["good", "broken"], status=JobStatus.RUNNING)
    runner = _make_runner(session_factory, registry)
    await runner.run_job(job_id)

    job = await _get_job(session_factory, job_id)
    assert job.status == JobStatus.COMPLETED_WITH_WARNINGS
    runs = {r.collector: r for r in await _get_collector_runs(session_factory, job_id)}
    assert runs["broken"].status == CollectorStatus.FAILED
    assert runs["broken"].safe_error_code == "unexpected_error"
    assert "boom" not in (runs["broken"].safe_error_message or "")  # no raw exception text leaked


@pytest.mark.asyncio
async def test_all_collectors_failing_marks_job_failed(session_factory) -> None:
    broken = ScriptedCollector("broken")

    async def _raise(ctx):
        raise RuntimeError("boom")

    broken.on_run = _raise
    registry = CollectorRegistry()
    registry.register(broken, allow_test_only=True)

    job_id = await _create_job(session_factory, target_type=TargetType.IP, target_normalized=PUBLIC_TEST_IP, collector_names=["broken"], status=JobStatus.RUNNING)
    runner = _make_runner(session_factory, registry)
    await runner.run_job(job_id)

    job = await _get_job(session_factory, job_id)
    assert job.status == JobStatus.FAILED


@pytest.mark.asyncio
async def test_target_not_applicable_collector_does_not_fail_the_job(session_factory) -> None:
    domain_only = ScriptedCollector("domain-only", supported=frozenset({TargetType.DOMAIN}))
    registry = CollectorRegistry()
    registry.register(domain_only, allow_test_only=True)

    job_id = await _create_job(session_factory, target_type=TargetType.IP, target_normalized=PUBLIC_TEST_IP, collector_names=["domain-only"], status=JobStatus.RUNNING)
    runner = _make_runner(session_factory, registry)
    await runner.run_job(job_id)

    job = await _get_job(session_factory, job_id)
    assert job.status == JobStatus.COMPLETED
    runs = await _get_collector_runs(session_factory, job_id)
    assert runs[0].status == CollectorStatus.NOT_APPLICABLE
    assert domain_only.calls == 0  # run() must never be called for an inapplicable target


@pytest.mark.asyncio
async def test_concurrency_limit_is_respected(session_factory) -> None:
    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def _tracked(ctx):
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.02)
        async with lock:
            in_flight -= 1
        return []

    names = ["c1", "c2", "c3", "c4"]
    registry = CollectorRegistry()
    for name in names:
        c = ScriptedCollector(name)
        c.on_run = _tracked
        registry.register(c, allow_test_only=True)

    job_id = await _create_job(session_factory, target_type=TargetType.IP, target_normalized=PUBLIC_TEST_IP, collector_names=names, status=JobStatus.RUNNING)
    runner = _make_runner(session_factory, registry, max_concurrent_collectors_per_job=2)
    await runner.run_job(job_id)

    assert max_in_flight <= 2
    job = await _get_job(session_factory, job_id)
    assert job.status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_cancellation_stops_further_dispatch_and_marks_job_canceled(session_factory) -> None:
    started = asyncio.Event()

    async def _slow(ctx):
        started.set()
        await asyncio.sleep(1)
        return []

    slow = ScriptedCollector("slow")
    slow.on_run = _slow
    never_started = ScriptedCollector("never-started")

    registry = CollectorRegistry()
    registry.register(slow, allow_test_only=True)
    registry.register(never_started, allow_test_only=True)

    job_id = await _create_job(
        session_factory, target_type=TargetType.IP, target_normalized=PUBLIC_TEST_IP,
        collector_names=["slow", "never-started"], status=JobStatus.RUNNING,
    )
    runner = _make_runner(session_factory, registry, max_concurrent_collectors_per_job=1)

    run_task = asyncio.create_task(runner.run_job(job_id))
    await started.wait()
    cancelled = await runner.request_cancellation(job_id)
    assert cancelled
    await run_task

    job = await _get_job(session_factory, job_id)
    assert job.status == JobStatus.CANCELED
    runs = {r.collector: r for r in await _get_collector_runs(session_factory, job_id)}
    assert runs["never-started"].status == CollectorStatus.FAILED
    assert runs["never-started"].safe_error_code == "cancelled"


@pytest.mark.asyncio
async def test_cancelling_a_still_queued_job_needs_no_runner_involvement(session_factory) -> None:
    job_id = await _create_job(session_factory, target_type=TargetType.IP, target_normalized=PUBLIC_TEST_IP, collector_names=["whatever"])
    runner = _make_runner(session_factory, CollectorRegistry())

    assert await runner.request_cancellation(job_id)
    job = await _get_job(session_factory, job_id)
    assert job.status == JobStatus.CANCELED


@pytest.mark.asyncio
async def test_restart_recovery_resumes_an_interrupted_collector(session_factory) -> None:
    collector = ScriptedCollector("resumable")
    collector.on_run = lambda ctx: asyncio.sleep(0, result=[_finding("resumed")])
    registry = CollectorRegistry()
    registry.register(collector, allow_test_only=True)

    job_id = await _create_job(
        session_factory, target_type=TargetType.IP, target_normalized=PUBLIC_TEST_IP,
        collector_names=["resumable"], status=JobStatus.RUNNING,
    )
    # Simulate a crash mid-collector-run: the row is stuck RUNNING with no
    # finished_at, exactly what a killed process would leave behind.
    runs = await _get_collector_runs(session_factory, job_id)
    async with session_factory() as session:
        async with session.begin():
            run = await session.get(CollectorRun, runs[0].id)
            run.status = CollectorStatus.RUNNING
            run.started_at = utcnow()

    runner = _make_runner(session_factory, registry)
    await runner.recover_on_startup()

    runs_after_recovery = await _get_collector_runs(session_factory, job_id)
    assert runs_after_recovery[0].status == CollectorStatus.INTERRUPTED

    resumable_ids = await runner.find_resumable_job_ids()
    assert job_id in resumable_ids

    await runner.run_job(job_id)

    job = await _get_job(session_factory, job_id)
    assert job.status == JobStatus.COMPLETED
    final_runs = await _get_collector_runs(session_factory, job_id)
    assert final_runs[0].status == CollectorStatus.DONE
    assert collector.calls == 1


@pytest.mark.asyncio
async def test_cidr_target_seeds_deny_list_without_any_gateway_call(session_factory) -> None:
    """CIDR/IP deny-list seeding is pure local ipaddress parsing - proves the
    fake gateway's never_called_transport is genuinely never invoked."""
    collector = ScriptedCollector("succeeds", supported=frozenset({TargetType.CIDR}))
    collector.on_run = lambda ctx: asyncio.sleep(0, result=[])
    registry = CollectorRegistry()
    registry.register(collector, allow_test_only=True)

    job_id = await _create_job(
        session_factory, target_type=TargetType.CIDR, target_normalized="203.0.113.0/24",
        collector_names=["succeeds"], status=JobStatus.RUNNING,
    )
    runner = _make_runner(session_factory, registry)
    await runner.run_job(job_id)  # would raise AssertionError from the fake transport if it were ever called

    job = await _get_job(session_factory, job_id)
    assert job.status == JobStatus.COMPLETED
