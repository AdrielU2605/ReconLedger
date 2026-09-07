"""Job creation (PRD FR-01, UX-03): the server-side authority for target
validation, source selection, and the authorization attestation. The
frontend's own validation/disabled-launch-button UX is a convenience, not the
boundary - this is.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.registry import CollectorRegistry
from app.db.base import new_uuid, utcnow
from app.models.api import JobCreateRequest
from app.models.db import CollectorRun, Job
from app.models.enums import CollectorStatus, JobStatus
from app.security.targets import TargetValidationError, classify_target

ATTESTATION_VERSION = "1.0"
ATTESTATION_TEXT = (
    "I own this target, or I have written authorization from its owner, to conduct "
    "a passive reconnaissance assessment against it using only third-party data providers."
)


class JobCreationError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def create_job(session: AsyncSession, request: JobCreateRequest, registry: CollectorRegistry) -> Job:
    if not request.attestation_confirmed:
        raise JobCreationError(
            "You must confirm ownership or written authorization before launching a job."
        )

    try:
        target = classify_target(request.target)
    except TargetValidationError as exc:
        raise JobCreationError(exc.reason) from exc

    if not target.assessable:
        raise JobCreationError(target.explanation or "This target type is not assessable in the MVP.")

    known_names = {c.metadata.name for c in registry.all()}
    unknown = [name for name in request.selected_sources if name not in known_names]
    if unknown:
        raise JobCreationError(f"Unknown source(s): {', '.join(unknown)}")

    job_id = new_uuid()
    now = utcnow()
    async with session.begin():
        session.add(
            Job(
                id=job_id,
                target_input=request.target,
                target_normalized=target.normalized,
                target_type=target.target_type,
                status=JobStatus.QUEUED,
                scope_note=request.scope_note,
                attestation_text=ATTESTATION_TEXT,
                attestation_version=ATTESTATION_VERSION,
                attestation_time=now,
                selected_sources_json=request.selected_sources,
                created_at=now,
            )
        )
        for name in request.selected_sources:
            session.add(CollectorRun(id=new_uuid(), job_id=job_id, collector=name, status=CollectorStatus.QUEUED))

    job = await session.get(Job, job_id)
    assert job is not None
    return job
