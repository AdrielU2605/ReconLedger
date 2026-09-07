from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.collectors.registry import CollectorRegistry
from app.jobs.runner import JobRunner


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = get_session_factory(request)
    async with session_factory() as session:
        yield session


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return cast("async_sessionmaker[AsyncSession]", request.app.state.session_factory)


def get_registry(request: Request) -> CollectorRegistry:
    return cast(CollectorRegistry, request.app.state.registry)


def get_runner(request: Request) -> JobRunner:
    return cast(JobRunner, request.app.state.runner)
