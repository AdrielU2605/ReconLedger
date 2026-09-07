"""SQLite has no real timestamp-with-timezone type: SQLAlchemy's
DateTime(timezone=True) accepts an aware datetime on write but silently
hands back a naive one on read, because there is nothing in SQLite storage
to reconstruct tzinfo from. Comparing that naive value against utcnow()
(always aware) then raises TypeError - this type makes every datetime this
app touches UTC and aware on both sides, always (FR-06: 'All timestamps are
stored as UTC ISO 8601').
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.engine import Dialect
from sqlalchemy.types import DateTime, TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        parsed: datetime = value
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
