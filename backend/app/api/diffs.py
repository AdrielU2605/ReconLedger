"""GET /api/jobs/{id}/diff (UX-09)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.models.api import DiffChangedPair, DiffFindingRead, DiffResponse
from app.services.diff import DiffFinding, DiffTargetMismatchError, JobNotFoundError, diff_jobs

router = APIRouter(tags=["diffs"])


@router.get("/api/jobs/{job_id}/diff", response_model=DiffResponse)
async def diff_job(job_id: str, against: str, session: AsyncSession = Depends(get_session)) -> DiffResponse:
    try:
        result = await diff_jobs(session, new_job_id=job_id, old_job_id=against)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DiffTargetMismatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    def _to_read(f: DiffFinding) -> DiffFindingRead:
        return DiffFindingRead(
            fingerprint=f.fingerprint, collector=f.collector, kind=f.kind,
            title=f.title, summary=f.summary, normalized_value=f.normalized_value,
        )

    return DiffResponse(
        added=[_to_read(f) for f in result.added],
        removed=[_to_read(f) for f in result.removed],
        changed=[DiffChangedPair(old=_to_read(o), new=_to_read(n)) for o, n in result.changed],
        unchanged_count=result.unchanged_count,
        indeterminate=[_to_read(f) for f in result.indeterminate],
    )
