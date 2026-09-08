"""GET/DELETE /api/cache (PRD 7.4, FR-12): inventory before purge, and a
manual full purge, exercised through the real FastAPI app rather than the
service functions directly."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.collectors.registry import CollectorRegistry
from app.config import Settings
from app.db.session import create_engine, enable_wal_mode, make_session_factory
from app.main import create_app
from app.security.gateway import OutboundGateway
from app.security.network import StaticResolver
from app.services.cache import CACHE_STATUS_SUCCESS, CacheAccess, compute_cache_key


def _never_called_gateway_factory(settings: Settings) -> OutboundGateway:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected provider request to {request.url}")

    return OutboundGateway(transport=httpx.MockTransport(handler), resolver=StaticResolver(table={}), settings=settings)


@pytest.fixture
def client(db_url: str, tmp_path):
    settings = Settings(_env_file=None, database_url=db_url, worker_lock_path=str(tmp_path / "worker.lock"))
    app = create_app(settings, registry=CollectorRegistry(), gateway_factory=_never_called_gateway_factory)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
async def session_factory(db_url: str):
    # A second connection onto the same on-disk (via db_url) database the
    # app under test is using, so tests can seed cache rows directly
    # without going through a collector run.
    engine = create_engine(db_url)
    async with enable_wal_mode(engine):
        pass
    factory = make_session_factory(engine)
    yield factory
    await engine.dispose()


def test_cache_inventory_is_empty_for_a_fresh_database(client: TestClient) -> None:
    resp = client.get("/api/cache")
    assert resp.status_code == 200
    assert resp.json() == {"total_entries": 0, "expired_entries": 0, "size_bytes": 0, "by_collector": []}


@pytest.mark.asyncio
async def test_cache_inventory_reflects_stored_entries(client: TestClient, session_factory) -> None:
    cache = CacheAccess(session_factory=session_factory, collector="rdap", schema_version="1")
    await cache.set(
        compute_cache_key(collector="rdap", schema_version="1", target_normalized="example.com"),
        status=CACHE_STATUS_SUCCESS, response_json={"a": 1}, normalized_findings_json={}, ttl_seconds=3600,
    )

    resp = client.get("/api/cache")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_entries"] == 1
    assert body["expired_entries"] == 0
    assert body["by_collector"] == [{"collector": "rdap", "count": 1}]


@pytest.mark.asyncio
async def test_delete_cache_purges_everything(client: TestClient, session_factory) -> None:
    cache = CacheAccess(session_factory=session_factory, collector="rdap", schema_version="1")
    await cache.set(
        compute_cache_key(collector="rdap", schema_version="1", target_normalized="example.com"),
        status=CACHE_STATUS_SUCCESS, response_json={}, normalized_findings_json={}, ttl_seconds=3600,
    )

    delete_resp = client.delete("/api/cache", headers={"Origin": "http://localhost:5173"})
    assert delete_resp.status_code == 204

    assert client.get("/api/cache").json()["total_entries"] == 0


def test_delete_cache_rejects_a_disallowed_origin(client: TestClient) -> None:
    resp = client.delete("/api/cache", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
