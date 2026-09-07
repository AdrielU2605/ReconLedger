"""Read-only access to a job's own already-persisted findings, for the one
collector that needs it: technology inference (FR-10) derives its results
from other collectors' evidence and must never make a network call of its
own. This is deliberately narrow - a query scoped to one job's rows, not
general database access - and is never used to reach outside the
requesting collector's own job.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.db import Finding


@dataclass
class JobFindingsReader:
    session_factory: async_sessionmaker[AsyncSession]
    job_id: str

    async def get(self, *, kinds: set[str] | None = None) -> list[Finding]:
        async with self.session_factory() as session:
            query = select(Finding).where(Finding.job_id == self.job_id)
            if kinds:
                query = query.where(Finding.kind.in_(kinds))
            result = await session.execute(query)
            return list(result.scalars().all())
