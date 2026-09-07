"""GET /api/sources: the source catalog and readiness (PRD 7.4, UX-04).

8.3: readiness reports only configured/not-configured/invalid-entitlement -
never a key prefix, length, or any part of the credential value.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from app.api.dependencies import get_registry
from app.collectors.registry import CollectorRegistry
from app.models.api import SourceRead

router = APIRouter(tags=["sources"])


def _state_for(required_credentials: tuple[str, ...]) -> str:
    if not required_credentials:
        return "ready"
    missing = [name for name in required_credentials if not os.environ.get(name)]
    return "missing_key" if missing else "ready"


@router.get("/api/sources", response_model=list[SourceRead])
async def list_sources(registry: CollectorRegistry = Depends(get_registry)) -> list[SourceRead]:
    return [
        SourceRead(
            name=collector.metadata.name,
            display_name=collector.metadata.display_name,
            supported_targets=sorted(collector.metadata.supported_targets, key=lambda t: t.value),
            categories=sorted(collector.metadata.categories, key=lambda c: c.value),
            release="mvp" if not collector.metadata.required_credentials else "1.1",
            state=_state_for(collector.metadata.required_credentials),
            key_help_url=collector.metadata.key_help_url,
        )
        for collector in registry.all()
    ]
