"""Job CRUD, cancellation, and SSE progress (PRD 7.4 core API contract)."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import StreamingResponse

from app.api.dependencies import get_registry, get_runner, get_session, get_session_factory
from app.collectors.registry import CollectorRegistry
from app.jobs.runner import JobRunner
from app.jobs.service import JobCreationError, create_job
from app.models.api import FindingRead, JobCreateRequest, JobDetail, JobSummary
from app.models.db import Finding, Job, JobEvent
from app.models.enums import TERMINAL_JOB_STATUSES
from app.security.origins import enforce_local_origin_and_content_type

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
async def list_jobs(session: AsyncSession = Depends(get_session)) -> list[Job]:
    result = await session.execute(select(Job).order_by(Job.created_at.desc()))
    return list(result.scalars().all())


@router.get("/api/jobs/{job_id}", response_model=JobDetail)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} does not exist.")
    await session.refresh(job, attribute_names=["collector_runs"])
    return job


@router.get("/api/jobs/{job_id}/findings", response_model=list[FindingRead])
async def list_findings(job_id: str, session: AsyncSession = Depends(get_session)) -> list[Finding]:
    """Unfiltered listing for CP4's evidence view. Search and filtering
    (UX-08) are added in CP5 once the FTS5 projection has a consumer."""
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} does not exist.")
    result = await session.execute(
        select(Finding).where(Finding.job_id == job_id).order_by(Finding.category, Finding.retrieved_at)
    )
    return list(result.scalars().all())


@router.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, runner: JobRunner = Depends(get_runner)) -> dict[str, str]:
    cancelled = await runner.request_cancellation(job_id)
    if not cancelled:
        raise HTTPException(
            status_code=409,
            detail="Job does not exist, or is not in a cancellable (queued/running) state.",
        )
    return {"status": "cancellation_requested"}


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
