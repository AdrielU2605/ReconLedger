"""FastAPI app factory.

Wires the single-process durable worker (9 Process model) into the API
process's own lifespan: one worker-exclusivity lock, startup crash recovery,
and a small in-process polling loop per allowed concurrent job - no Redis,
no separate worker process.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api import diffs as diffs_api
from app.api import exports as exports_api
from app.api import jobs as jobs_api
from app.api import sources as sources_api
from app.collectors.registry import CollectorRegistry, get_production_registry
from app.config import Settings, get_settings
from app.db.session import create_engine, enable_wal_mode, make_session_factory
from app.jobs.runner import GatewayFactory, JobRunner
from app.jobs.worker_lock import WorkerLock
from app.logging_config import configure_logging
from app.security.gateway import build_production_gateway

logger = logging.getLogger("reconledger.main")

WORKER_IDLE_POLL_SECONDS = 0.5


async def _worker_loop(runner: JobRunner) -> None:
    while True:
        job_id = await runner.claim_next_queued_job()
        if job_id is None:
            await asyncio.sleep(WORKER_IDLE_POLL_SECONDS)
            continue
        await runner.run_job(job_id)


def create_app(
    settings: Settings | None = None,
    *,
    registry: CollectorRegistry | None = None,
    gateway_factory: GatewayFactory = build_production_gateway,
) -> FastAPI:
    """`gateway_factory` exists so tests can inject a fully mocked gateway -
    every real collector run in this app's tests must be as hermetic as the
    gateway's own unit tests, with no exception for "just the API layer"."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        async with enable_wal_mode(engine):
            pass
        session_factory = make_session_factory(engine)
        active_registry = registry or get_production_registry()
        runner = JobRunner(
            session_factory=session_factory,
            registry=active_registry,
            settings=settings,
            gateway_factory=gateway_factory,
        )

        lock = WorkerLock(Path(settings.worker_lock_path))
        lock.acquire(external_worker_configured=settings.external_worker_configured)

        await runner.recover_on_startup()
        resumable_job_ids = await runner.find_resumable_job_ids()

        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.registry = active_registry
        app.state.runner = runner

        background_tasks = [asyncio.create_task(runner.run_job(job_id)) for job_id in resumable_job_ids]
        background_tasks.extend(
            asyncio.create_task(_worker_loop(runner)) for _ in range(settings.max_concurrent_jobs)
        )

        try:
            yield
        finally:
            for task in background_tasks:
                task.cancel()
            await asyncio.gather(*background_tasks, return_exceptions=True)
            lock.release()
            await engine.dispose()

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.include_router(sources_api.router)
    app.include_router(jobs_api.router)
    app.include_router(exports_api.router)
    app.include_router(diffs_api.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


_settings = get_settings()
configure_logging(_settings.log_level)
app = create_app(_settings)
