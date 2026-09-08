"""GET/DELETE /api/cache (PRD 7.4, FR-12): inventory before purge, and a
manual full purge - independent of the automatic retention sweep, which
only removes entries once they've already expired."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.models.api import CacheInventoryRead
from app.security.origins import enforce_local_origin_and_content_type
from app.services.cache import inventory as cache_inventory
from app.services.cache import purge_all as cache_purge_all

router = APIRouter(tags=["cache"], dependencies=[Depends(enforce_local_origin_and_content_type)])


@router.get("/api/cache", response_model=CacheInventoryRead)
async def get_cache_inventory(session: AsyncSession = Depends(get_session)) -> CacheInventoryRead:
    return await cache_inventory(session)


@router.delete("/api/cache", status_code=204, response_model=None)
async def delete_cache(session: AsyncSession = Depends(get_session)) -> None:
    await cache_purge_all(session)
