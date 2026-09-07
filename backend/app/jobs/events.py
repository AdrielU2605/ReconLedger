"""Job progress events (PRD 7.3 Progress, 7.4 GET /api/jobs/{id}/events).

SSE is advisory; the authoritative state always lives on Job/CollectorRun
rows. Every event this module writes is just a notification that those rows
changed, with a monotonically increasing id usable as a Last-Event-ID for
SSE reconnect.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models.db import JobEvent


async def emit(
    session: AsyncSession,
    *,
    job_id: str,
    event_type: str,
    collector: str | None = None,
    payload: dict[str, Any] | None = None,
) -> JobEvent:
    event = JobEvent(
        job_id=job_id,
        collector=collector,
        event_type=event_type,
        payload_json=payload or {},
        created_at=utcnow(),
    )
    session.add(event)
    await session.flush()
    return event
