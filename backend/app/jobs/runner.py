"""The job runner (PRD FR-01, 7.2, 7.3).

Claims queued jobs transactionally, resolves the target and seeds its
deny-list before dispatching any collector, runs collectors with bounded
concurrency, persists findings and progress events, resumes interrupted work
after a restart, and computes the job's final status.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.collectors.base import CollectedFinding, CollectorContext
from app.collectors.errors import CollectorError, TargetNotApplicableError, translate_gateway_error
from app.collectors.registry import CollectorRegistry
from app.config import Settings
from app.db.base import utcnow
from app.jobs import events
from app.jobs.deny_list import seed_deny_list_for_target
from app.models.db import CollectorRun, Finding, Job
from app.models.enums import CollectorStatus, JobStatus
from app.security.errors import GatewayError
from app.security.gateway import OutboundGateway, build_production_gateway
from app.security.targets import ClassifiedTarget

logger = logging.getLogger("reconledger.runner")

GatewayFactory = Callable[[Settings], OutboundGateway]


def _compute_job_status(collector_statuses: list[CollectorStatus]) -> JobStatus:
    """PRD 7.3: failed only when no selected collector produces a valid
    terminal result. A job where every collector was skipped/not-applicable
    (nothing failed, nothing succeeded either) is COMPLETED, not FAILED -
    there was no error, just nothing this set of sources could do."""
    has_done = CollectorStatus.DONE in collector_statuses
    has_failed = CollectorStatus.FAILED in collector_statuses
    if has_done and has_failed:
        return JobStatus.COMPLETED_WITH_WARNINGS
    if has_failed and not has_done:
        return JobStatus.FAILED
    return JobStatus.COMPLETED


class JobRunner:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        registry: CollectorRegistry,
        settings: Settings,
        gateway_factory: GatewayFactory = build_production_gateway,
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry
        self._settings = settings
        self._gateway_factory = gateway_factory
        self._cancellation_events: dict[str, asyncio.Event] = {}

    # -- startup recovery (FR-01) -----------------------------------------

    async def recover_on_startup(self) -> None:
        """Any CollectorRun still RUNNING when the process last stopped was
        orphaned by the crash/restart - it becomes INTERRUPTED so run_job
        picks it back up as pending work rather than leaving it stuck."""
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(CollectorRun)
                    .where(CollectorRun.status == CollectorStatus.RUNNING)
                    .values(status=CollectorStatus.INTERRUPTED)
                )

    async def find_resumable_job_ids(self) -> list[str]:
        """Jobs left RUNNING by a crash that still have non-terminal
        collector work (QUEUED or, after recovery, INTERRUPTED)."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Job.id)
                .join(CollectorRun, CollectorRun.job_id == Job.id)
                .where(
                    Job.status == JobStatus.RUNNING,
                    CollectorRun.status.in_([CollectorStatus.QUEUED, CollectorStatus.INTERRUPTED]),
                )
                .distinct()
            )
            return list(result.scalars().all())

    # -- claiming ------------------------------------------------------------

    async def claim_next_queued_job(self) -> str | None:
        """Transactionally claims one queued job. Returns None if there is
        none, or if a concurrent claimer won the race (single-process
        deployment makes that race theoretical, but the guard costs nothing)."""
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    select(Job.id).where(Job.status == JobStatus.QUEUED).order_by(Job.created_at).limit(1)
                )
                job_id = result.scalar_one_or_none()
                if job_id is None:
                    return None
                update_result = await session.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == JobStatus.QUEUED)
                    .values(status=JobStatus.RUNNING, started_at=utcnow())
                )
                if update_result.rowcount != 1:  # type: ignore[attr-defined]
                    return None
        return job_id

    # -- cancellation ----------------------------------------------------

    async def request_cancellation(self, job_id: str) -> bool:
        """Returns True if cancellation was applied. A QUEUED job is
        cancelled immediately (nothing to interrupt); a RUNNING job has its
        in-memory cancellation Event set so run_job stops dispatching further
        collectors and marks in-flight ones failed with a 'cancelled' reason."""
        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(Job, job_id)
                if job is None:
                    return False
                if job.status == JobStatus.QUEUED:
                    job.status = JobStatus.CANCELED
                    job.finished_at = utcnow()
                    await events.emit(session, job_id=job_id, event_type="job_finished", payload={"status": "canceled"})
                    return True
                if job.status != JobStatus.RUNNING:
                    return False
        cancellation = self._cancellation_events.get(job_id)
        if cancellation is None:
            return False
        cancellation.set()
        return True

    # -- dispatch ----------------------------------------------------------

    async def run_job(self, job_id: str) -> None:
        cancellation = asyncio.Event()
        self._cancellation_events[job_id] = cancellation
        try:
            async with self._session_factory() as session:
                job = await session.get(Job, job_id)
                if job is None:
                    return
                target = ClassifiedTarget(
                    target_type=job.target_type,
                    original_input=job.target_input,
                    normalized=job.target_normalized,
                )
                scope_note = job.scope_note
                result = await session.execute(
                    select(CollectorRun).where(
                        CollectorRun.job_id == job_id,
                        CollectorRun.status.in_([CollectorStatus.QUEUED, CollectorStatus.INTERRUPTED]),
                    )
                )
                pending = [(cr.id, cr.collector) for cr in result.scalars().all()]

            gateway = self._gateway_factory(self._settings)
            try:
                await seed_deny_list_for_target(gateway, target)
            except Exception:
                logger.exception("deny_list_seed_failed", extra={"job_id": job_id})
                await self._fail_job_before_dispatch(job_id, pending, "deny_list_seed_failed")
                return

            semaphore = asyncio.Semaphore(self._settings.max_concurrent_collectors_per_job)

            async def _bounded(collector_run_id: str, collector_name: str) -> None:
                async with semaphore:
                    await self._run_one_collector(
                        job_id=job_id,
                        collector_run_id=collector_run_id,
                        collector_name=collector_name,
                        target=target,
                        scope_note=scope_note,
                        gateway=gateway,
                        cancellation=cancellation,
                    )

            if pending:
                await asyncio.gather(*(_bounded(cr_id, name) for cr_id, name in pending))
            await gateway.aclose()
            await self._finalize_job(job_id, cancellation)
        finally:
            self._cancellation_events.pop(job_id, None)

    async def _fail_job_before_dispatch(self, job_id: str, pending: list[tuple[str, str]], safe_error_code: str) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                for collector_run_id, _name in pending:
                    await session.execute(
                        update(CollectorRun)
                        .where(CollectorRun.id == collector_run_id)
                        .values(
                            status=CollectorStatus.FAILED,
                            finished_at=utcnow(),
                            safe_error_code=safe_error_code,
                            safe_error_message="Could not establish the safety boundary for this target.",
                        )
                    )
                await session.execute(
                    update(Job).where(Job.id == job_id).values(status=JobStatus.FAILED, finished_at=utcnow())
                )
                await events.emit(session, job_id=job_id, event_type="job_finished", payload={"status": "failed"})

    async def _run_one_collector(
        self,
        *,
        job_id: str,
        collector_run_id: str,
        collector_name: str,
        target: ClassifiedTarget,
        scope_note: str | None,
        gateway: OutboundGateway,
        cancellation: asyncio.Event,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                run = await session.get(CollectorRun, collector_run_id)
                assert run is not None
                run.status = CollectorStatus.RUNNING
                run.started_at = utcnow()
                run.attempt_count += 1
                await events.emit(session, job_id=job_id, collector=collector_name, event_type="collector_started")

        try:
            collector = self._registry.get(collector_name)
        except KeyError:
            await self._finish_collector(job_id, collector_run_id, collector_name, CollectorStatus.FAILED, "unknown_collector", f"{collector_name!r} is not a registered collector.", 0)
            return

        if target.target_type not in collector.metadata.supported_targets:
            error = TargetNotApplicableError(collector_name, target.target_type.value)
            await self._finish_collector(job_id, collector_run_id, collector_name, error.resulting_status, error.safe_error_code, error.safe_error_message, 0)
            return

        if cancellation.is_set():
            await self._finish_collector(job_id, collector_run_id, collector_name, CollectorStatus.FAILED, "cancelled", f"{collector_name} was cancelled.", 0)
            return

        context = CollectorContext(
            job_id=job_id,
            target=target,
            scope_note=scope_note,
            gateway=gateway,
            cancellation=cancellation,
            job_deadline_monotonic=time.monotonic() + self._settings.job_budget_seconds,
            collector_budget_seconds=self._settings.collector_budget_seconds,
        )

        findings: list[CollectedFinding]
        try:
            findings = await collector.run(context)
        except CollectorError as exc:
            await self._finish_collector(job_id, collector_run_id, collector_name, exc.resulting_status, exc.safe_error_code, exc.safe_error_message, 0)
            return
        except GatewayError as exc:
            translated = translate_gateway_error(collector_name, exc)
            await self._finish_collector(job_id, collector_run_id, collector_name, translated.resulting_status, translated.safe_error_code, translated.safe_error_message, 0)
            return
        except Exception:
            logger.exception("collector_unexpected_error", extra={"collector": collector_name, "job_id": job_id})
            await self._finish_collector(job_id, collector_run_id, collector_name, CollectorStatus.FAILED, "unexpected_error", "An unexpected internal error occurred.", 0)
            return

        async with self._session_factory() as session:
            async with session.begin():
                for cf in findings:
                    session.add(
                        Finding(
                            job_id=job_id,
                            collector=collector_name,
                            category=cf.category,
                            kind=cf.kind,
                            title=cf.title,
                            summary=cf.summary,
                            normalized_value_json=cf.normalized_value,
                            raw_evidence_json=cf.raw_evidence,
                            source_url=cf.source_url,
                            provider_observed_at=cf.provider_observed_at,
                            retrieved_at=cf.retrieved_at,
                            confidence=cf.confidence,
                            fingerprint=cf.fingerprint,
                        )
                    )
        await self._finish_collector(job_id, collector_run_id, collector_name, CollectorStatus.DONE, None, None, len(findings))

    async def _finish_collector(
        self,
        job_id: str,
        collector_run_id: str,
        collector_name: str,
        status: CollectorStatus,
        safe_error_code: str | None,
        safe_error_message: str | None,
        finding_count: int,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(CollectorRun)
                    .where(CollectorRun.id == collector_run_id)
                    .values(
                        status=status,
                        finished_at=utcnow(),
                        safe_error_code=safe_error_code,
                        safe_error_message=safe_error_message,
                        finding_count=finding_count,
                    )
                )
                await events.emit(
                    session,
                    job_id=job_id,
                    collector=collector_name,
                    event_type="collector_finished",
                    payload={"status": status.value, "finding_count": finding_count},
                )

    async def _finalize_job(self, job_id: str, cancellation: asyncio.Event) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(select(CollectorRun.status).where(CollectorRun.job_id == job_id))
                statuses = list(result.scalars().all())
                final_status = JobStatus.CANCELED if cancellation.is_set() else _compute_job_status(statuses)
                await session.execute(
                    update(Job).where(Job.id == job_id).values(status=final_status, finished_at=utcnow())
                )
                await events.emit(session, job_id=job_id, event_type="job_finished", payload={"status": final_status.value})
