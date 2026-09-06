"""FastAPI app factory.

CP1 scope only: settings, logging, and a liveness check. The real API surface
(jobs, sources, exports, diffs) is built in CP2 once persistence exists.
"""
from __future__ import annotations

from fastapi import FastAPI

from app.config import get_settings
from app.logging_config import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(title=settings.app_name, version=settings.app_version)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
