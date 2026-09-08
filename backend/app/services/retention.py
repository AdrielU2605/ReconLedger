"""FR-12: retention and cache-expiry sweep.

Runs at application startup and after every job reaches a terminal state
(PRD 6/7.2) - retention is never left to a manual action. A job (and its
collector_runs/findings/job_events, which cascade via ondelete=CASCADE)
counts toward retention once it has *finished*: an old but still
queued/running job is never swept just because it's old, only because it's
been sitting in history past the retention window.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import utcnow
from app.models.db import CacheEntry, Job
from app.models.enums import TERMINAL_JOB_STATUSES

logger = logging.getLogger("reconledger.retention")


async def sweep(session_factory: async_sessionmaker[AsyncSession], *, retention_days: float) -> None:
    now = utcnow()
    cutoff = now - timedelta(days=retention_days)
    expired_jobs = Job.status.in_(TERMINAL_JOB_STATUSES) & (Job.finished_at < cutoff)
    expired_cache = CacheEntry.expires_at <= now

    async with session_factory() as session:
        async with session.begin():
            jobs_deleted = (await session.execute(select(func.count()).select_from(Job).where(expired_jobs))).scalar_one()
            cache_deleted = (
                await session.execute(select(func.count()).select_from(CacheEntry).where(expired_cache))
            ).scalar_one()
            await session.execute(delete(Job).where(expired_jobs))
            await session.execute(delete(CacheEntry).where(expired_cache))

    logger.info(
        "retention_sweep_completed",
        extra={"jobs_deleted": jobs_deleted, "cache_entries_deleted": cache_deleted, "retention_days": retention_days},
    )
