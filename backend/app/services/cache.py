"""FR-05: response cache.

Fresh entries eliminate outbound calls and produce a done-cached collector
state. Negative (empty) results may be cached briefly; authentication
failures and malformed responses are never written here at all, so the next
attempt is a normal cache miss rather than a cached failure.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import utcnow
from app.models.db import CacheEntry

CACHE_STATUS_SUCCESS = "success"
CACHE_STATUS_EMPTY = "empty"


def compute_cache_key(
    *, collector: str, schema_version: str, target_normalized: str, variant: str = "", credential_scope_hash: str | None = None
) -> str:
    canonical = "|".join(
        [collector, schema_version, target_normalized, variant, credential_scope_hash or ""]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class CacheAccess:
    """Bound to one collector run. Cache reads/writes are their own short
    transactions (PRD 11: short transactions, one writer path), independent
    of whatever transaction the caller might otherwise be in."""

    session_factory: async_sessionmaker[AsyncSession]
    collector: str
    schema_version: str

    async def get(self, cache_key: str) -> CacheEntry | None:
        async with self.session_factory() as session:
            entry = await session.get(CacheEntry, cache_key)
            if entry is None or entry.expires_at <= utcnow():
                return None
            return entry

    async def set(
        self,
        cache_key: str,
        *,
        status: str,
        response_json: dict[str, Any],
        normalized_findings_json: dict[str, Any],
        ttl_seconds: float,
        credential_scope_hash: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        now = utcnow()
        async with self.session_factory() as session:
            async with session.begin():
                await session.merge(
                    CacheEntry(
                        cache_key=cache_key,
                        collector=self.collector,
                        schema_version=self.schema_version,
                        credential_scope_hash=credential_scope_hash,
                        status=status,
                        response_json=response_json,
                        normalized_findings_json=normalized_findings_json,
                        retrieved_at=now,
                        expires_at=now + timedelta(seconds=ttl_seconds),
                        etag=etag,
                        last_modified=last_modified,
                    )
                )
