"""GET /api/jobs/{id}/export (FR-11): generated entirely from persisted
evidence, no provider calls."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse, PlainTextResponse, Response

from app.api.dependencies import get_session
from app.models.db import CollectorRun, Finding, Job
from app.services.reports import ExportBundle, build_json_export, build_markdown_export

router = APIRouter(tags=["exports"])


@router.get("/api/jobs/{job_id}/export", response_model=None)
async def export_job(
    job_id: str,
    format: Literal["md", "json"] = "json",
    mode: Literal["summary", "full"] = "full",
    session: AsyncSession = Depends(get_session),
) -> Response:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} does not exist.")

    collector_runs = (
        await session.execute(select(CollectorRun).where(CollectorRun.job_id == job_id))
    ).scalars().all()
    findings = (await session.execute(select(Finding).where(Finding.job_id == job_id))).scalars().all()
    bundle = ExportBundle(job=job, collector_runs=list(collector_runs), findings=list(findings))

    if format == "json":
        return JSONResponse(build_json_export(bundle))
    return PlainTextResponse(build_markdown_export(bundle, mode=mode), media_type="text/markdown; charset=utf-8")
