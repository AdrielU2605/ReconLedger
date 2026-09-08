"""Job CRUD, cancellation, and SSE progress (PRD 7.4 core API contract)."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import PlainTextResponse, StreamingResponse

from app.api.dependencies import get_registry, get_runner, get_session, get_session_factory
from app.collectors.registry import CollectorRegistry
from app.jobs.runner import JobRunner
from app.jobs.service import JobCreationError, create_job
from app.models.api import FindingRead, JobCreateRequest, JobDetail, JobSummary, SubdomainRowRead
from app.models.db import CollectorRun, Finding, Job, JobEvent
from app.models.enums import TERMINAL_JOB_STATUSES, Category, CollectorStatus, JobStatus
from app.security.origins import enforce_local_origin_and_content_type
from app.services.csv_export import build_subdomains_csv
from app.services.search import find_matching_finding_ids
from app.services.subdomains import SubdomainRow, aggregate_subdomains

router = APIRouter(tags=["jobs"], dependencies=[Depends(enforce_local_origin_and_content_type)])

SSE_POLL_INTERVAL_SECONDS = 0.5


@router.post("/api/jobs", response_model=JobDetail, status_code=202)
async def create_job_endpoint(
    payload: JobCreateRequest,
    session: AsyncSession = Depends(get_session),
    registry: CollectorRegistry = Depends(get_registry),
) -> Job:
    try:
        job = await create_job(session, payload, registry)
    except JobCreationError as exc:
        raise HTTPException(status_code=422, detail=exc.reason) from exc
    await session.refresh(job, attribute_names=["collector_runs"])
    return job


@router.get("/api/jobs", response_model=list[JobSummary])
async def list_jobs(session: AsyncSession = Depends(get_session)) -> list[JobSummary]:
    """UX-09 history: target, type, status, time, selected sources, and a
    warning count (failed collector runs) - the last one computed here via
    an aggregate join rather than loading every job's full collector_runs
    list, which is what makes JobDetail heavier than JobSummary."""
    warning_counts = (
        select(CollectorRun.job_id, func.count(CollectorRun.id).label("warning_count"))
        .where(CollectorRun.status == CollectorStatus.FAILED)
        .group_by(CollectorRun.job_id)
        .subquery()
    )
    result = await session.execute(
        select(Job, func.coalesce(warning_counts.c.warning_count, 0))
        .outerjoin(warning_counts, warning_counts.c.job_id == Job.id)
        .order_by(Job.created_at.desc())
    )
    summaries = []
    for job, warning_count in result.all():
        summary = JobSummary.model_validate(job)
        summary.warning_count = warning_count
        summaries.append(summary)
    return summaries


@router.get("/api/jobs/{job_id}", response_model=JobDetail)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} does not exist.")
    await session.refresh(job, attribute_names=["collector_runs"])
    return job


@router.get("/api/jobs/{job_id}/findings", response_model=list[FindingRead])
async def list_findings(
    job_id: str,
    q: str | None = None,
    category: Category | None = None,
    collector: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[Finding]:
    """UX-08: global search (q, matched via the findings_fts FTS5 projection)
    combined with category/source filters. Omitting all three params returns
    every finding in the job (CP4's original unfiltered behavior)."""
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} does not exist.")

    query = select(Finding).where(Finding.job_id == job_id)
    if q:
        matched_ids = await find_matching_finding_ids(session, job_id=job_id, query=q)
        if not matched_ids:
            return []
        query = query.where(Finding.id.in_(matched_ids))
    if category is not None:
        query = query.where(Finding.category == category)
    if collector is not None:
        query = query.where(Finding.collector == collector)

    result = await session.execute(query.order_by(Finding.category, Finding.retrieved_at))
    return list(result.scalars().all())


async def _get_subdomain_rows(job_id: str, session: AsyncSession) -> tuple[Job, list[SubdomainRow]]:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} does not exist.")
    result = await session.execute(select(Finding).where(Finding.job_id == job_id))
    findings = list(result.scalars().all())
    return job, aggregate_subdomains(job.target_normalized, findings)


@router.get("/api/jobs/{job_id}/subdomains", response_model=list[SubdomainRowRead])
async def list_subdomains(job_id: str, session: AsyncSession = Depends(get_session)) -> list[SubdomainRowRead]:
    _job, rows = await _get_subdomain_rows(job_id, session)
    return [SubdomainRowRead(**row.__dict__) for row in rows]


@router.get("/api/jobs/{job_id}/subdomains.csv", response_model=None)
async def export_subdomains_csv(job_id: str, session: AsyncSession = Depends(get_session)) -> PlainTextResponse:
    """FR-11: formula-safe UTF-8 CSV, generated entirely from persisted
    evidence - no provider calls."""
    _job, rows = await _get_subdomain_rows(job_id, session)
    csv_text = build_subdomains_csv(rows)
    return PlainTextResponse(
        csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="reconledger-{job_id}-subdomains.csv"'},
    )


@router.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, runner: JobRunner = Depends(get_runner)) -> dict[str, str]:
    cancelled = await runner.request_cancellation(job_id)
    if not cancelled:
        raise HTTPException(
            status_code=409,
            detail="Job does not exist, or is not in a cancellable (queued/running) state.",
        )
    return {"status": "cancellation_requested"}


@router.post("/api/jobs/{job_id}/collectors/{collector_name}/retry")
async def retry_collector(
    job_id: str,
    collector_name: str,
    session: AsyncSession = Depends(get_session),
    runner: JobRunner = Depends(get_runner),
) -> dict[str, str]:
    """PRD 7.4: retry a single failed collector without re-running the rest
    of the job. Re-queues the collector run and the job itself - the
    in-process worker loop (app.main._worker_loop) picks the job back up the
    same way it picks up any newly-created one, so this needs no direct call
    into the runner's dispatch path."""
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} does not exist.")
    if runner.is_active(job_id):
        raise HTTPException(status_code=409, detail="Job is currently being dispatched; try again shortly.")

    result = await session.execute(
        select(CollectorRun).where(CollectorRun.job_id == job_id, CollectorRun.collector == collector_name)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail=f"No collector named {collector_name!r} in this job.")
    if run.status != CollectorStatus.FAILED:
        raise HTTPException(
            status_code=409,
            detail=f"Collector {collector_name!r} is not in a retryable (failed) state.",
        )

    run.status = CollectorStatus.QUEUED
    run.started_at = None
    run.finished_at = None
    run.safe_error_code = None
    run.safe_error_message = None
    job.status = JobStatus.QUEUED
    job.started_at = None
    job.finished_at = None
    await session.commit()
    return {"status": "retry_queued"}


@router.delete("/api/jobs/{job_id}", status_code=204, response_model=None)
async def delete_job(job_id: str, session: AsyncSession = Depends(get_session)) -> None:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} does not exist.")
    # The session auto-begins on the get() above, so this commits that same
    # transaction rather than opening a second one.
    await session.delete(job)  # cascades to collector_runs/findings/events (FR-12)
    await session.commit()


async def _sse_event_stream(
    job_id: str, session_factory: async_sessionmaker[AsyncSession], last_event_id: int
) -> AsyncIterator[str]:
    seen_id = last_event_id
    while True:
        async with session_factory() as session:
            result = await session.execute(
                select(JobEvent).where(JobEvent.job_id == job_id, JobEvent.id > seen_id).order_by(JobEvent.id)
            )
            new_events = list(result.scalars().all())
            job = await session.get(Job, job_id)

        for event in new_events:
            seen_id = event.id
            payload = json.dumps(
                {
                    "event_type": event.event_type,
                    "collector": event.collector,
                    "payload": event.payload_json,
                    "created_at": event.created_at.isoformat(),
                }
            )
            yield f"id: {event.id}\ndata: {payload}\n\n"

        if job is None or job.status in TERMINAL_JOB_STATUSES:
            return
        await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)


@router.get("/api/jobs/{job_id}/events")
async def job_events(
    job_id: str,
    request: Request,
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> StreamingResponse:
    """SSE is advisory (7.3): this just streams job_events rows as they
    appear. GET /api/jobs/{id} remains authoritative, and Last-Event-ID
    support lets a client resume a dropped connection without missing events."""
    last_event_id = 0
    header_value = request.headers.get("last-event-id")
    if header_value is not None:
        try:
            last_event_id = int(header_value)
        except ValueError:
            last_event_id = 0

    return StreamingResponse(
        _sse_event_stream(job_id, session_factory, last_event_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
