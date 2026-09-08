"""Structured logging (PRD 9 Observability, 8.3 Secrets and logging).

Every log record carries job/collector/request correlation IDs when available,
and every rendered message and header dict is passed through the secret
registry before it leaves the process. No raw secrets are ever logged.
"""
from __future__ import annotations

import contextvars
import json
import logging
from typing import Any

from app.security.redaction import secret_registry

job_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("job_id", default=None)
collector_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("collector", default=None)
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


class CorrelationJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": secret_registry.redact(record.getMessage()),
            "job_id": job_id_var.get(),
            "collector": collector_var.get(),
            "request_id": request_id_var.get(),
        }
        for key in (
            "latency_ms", "attempt", "cache_outcome", "safe_error_code", "host",
            "jobs_deleted", "cache_entries_deleted", "retention_days",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc_info"] = secret_registry.redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(CorrelationJsonFormatter())
    root.addHandler(handler)


def bind_correlation(
    *, job_id: str | None = None, collector: str | None = None, request_id: str | None = None
) -> None:
    if job_id is not None:
        job_id_var.set(job_id)
    if collector is not None:
        collector_var.set(collector)
    if request_id is not None:
        request_id_var.set(request_id)
