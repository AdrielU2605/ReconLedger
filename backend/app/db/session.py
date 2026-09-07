from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

_ENGINE_KWARGS = {
    # SQLite: one writer at a time, but WAL lets readers proceed concurrently
    # with a writer (PRD 11 risk: "SQLite write contention").
    "connect_args": {"check_same_thread": False},
}


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, **_ENGINE_KWARGS)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def enable_wal_mode(engine: AsyncEngine) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    yield
