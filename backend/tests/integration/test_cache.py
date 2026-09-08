"""FR-05: cache hits eliminate outbound calls; negative (empty) results are
cacheable briefly; nothing is ever written for a failure."""
from __future__ import annotations

import pytest

from app.services.cache import (
    CACHE_STATUS_EMPTY,
    CACHE_STATUS_SUCCESS,
    CacheAccess,
    compute_cache_key,
    inventory,
    purge_all,
)


def test_cache_key_is_stable_and_input_sensitive() -> None:
    key1 = compute_cache_key(collector="rdap", schema_version="1", target_normalized="example.com")
    key2 = compute_cache_key(collector="rdap", schema_version="1", target_normalized="example.com")
    key3 = compute_cache_key(collector="rdap", schema_version="1", target_normalized="other.com")
    key4 = compute_cache_key(collector="rdap", schema_version="2", target_normalized="example.com")

    assert key1 == key2
    assert key1 != key3
    assert key1 != key4


@pytest.mark.asyncio
async def test_cache_miss_when_nothing_stored(session_factory) -> None:
    cache = CacheAccess(session_factory=session_factory, collector="rdap", schema_version="1")
    key = compute_cache_key(collector="rdap", schema_version="1", target_normalized="example.com")
    assert await cache.get(key) is None


@pytest.mark.asyncio
async def test_cache_set_then_get_is_a_hit(session_factory) -> None:
    cache = CacheAccess(session_factory=session_factory, collector="rdap", schema_version="1")
    key = compute_cache_key(collector="rdap", schema_version="1", target_normalized="example.com")

    await cache.set(
        key,
        status=CACHE_STATUS_SUCCESS,
        response_json={"raw": True},
        normalized_findings_json={"findings": [{"kind": "rdap.registrar"}]},
        ttl_seconds=86400,
    )

    entry = await cache.get(key)
    assert entry is not None
    assert entry.status == CACHE_STATUS_SUCCESS
    assert entry.normalized_findings_json == {"findings": [{"kind": "rdap.registrar"}]}


@pytest.mark.asyncio
async def test_expired_entry_is_a_miss(session_factory) -> None:
    cache = CacheAccess(session_factory=session_factory, collector="rdap", schema_version="1")
    key = compute_cache_key(collector="rdap", schema_version="1", target_normalized="example.com")

    await cache.set(
        key, status=CACHE_STATUS_SUCCESS, response_json={}, normalized_findings_json={}, ttl_seconds=-1
    )
    assert await cache.get(key) is None


@pytest.mark.asyncio
async def test_negative_empty_result_is_cacheable(session_factory) -> None:
    cache = CacheAccess(session_factory=session_factory, collector="crtsh", schema_version="1")
    key = compute_cache_key(collector="crtsh", schema_version="1", target_normalized="example.com")

    await cache.set(
        key, status=CACHE_STATUS_EMPTY, response_json={"raw": []}, normalized_findings_json={"findings": []},
        ttl_seconds=3600,
    )
    entry = await cache.get(key)
    assert entry is not None
    assert entry.status == CACHE_STATUS_EMPTY


@pytest.mark.asyncio
async def test_set_overwrites_previous_entry_for_the_same_key(session_factory) -> None:
    cache = CacheAccess(session_factory=session_factory, collector="rdap", schema_version="1")
    key = compute_cache_key(collector="rdap", schema_version="1", target_normalized="example.com")

    await cache.set(key, status=CACHE_STATUS_SUCCESS, response_json={"v": 1}, normalized_findings_json={}, ttl_seconds=3600)
    await cache.set(key, status=CACHE_STATUS_SUCCESS, response_json={"v": 2}, normalized_findings_json={}, ttl_seconds=3600)

    entry = await cache.get(key)
    assert entry is not None
    assert entry.response_json == {"v": 2}


@pytest.mark.asyncio
async def test_inventory_reports_totals_expiry_and_per_collector_breakdown(session_factory) -> None:
    rdap = CacheAccess(session_factory=session_factory, collector="rdap", schema_version="1")
    crtsh = CacheAccess(session_factory=session_factory, collector="crtsh", schema_version="1")

    await rdap.set(
        compute_cache_key(collector="rdap", schema_version="1", target_normalized="example.com"),
        status=CACHE_STATUS_SUCCESS, response_json={"a": 1}, normalized_findings_json={}, ttl_seconds=3600,
    )
    await crtsh.set(
        compute_cache_key(collector="crtsh", schema_version="1", target_normalized="example.com"),
        status=CACHE_STATUS_SUCCESS, response_json={"b": 2}, normalized_findings_json={}, ttl_seconds=3600,
    )
    await crtsh.set(
        compute_cache_key(collector="crtsh", schema_version="1", target_normalized="other.com"),
        status=CACHE_STATUS_SUCCESS, response_json={"c": 3}, normalized_findings_json={}, ttl_seconds=-1,  # already expired
    )

    async with session_factory() as session:
        result = await inventory(session)

    assert result.total_entries == 3
    assert result.expired_entries == 1
    assert result.size_bytes > 0
    by_collector = {row.collector: row.count for row in result.by_collector}
    assert by_collector == {"rdap": 1, "crtsh": 2}


@pytest.mark.asyncio
async def test_purge_all_removes_every_entry_regardless_of_expiry(session_factory) -> None:
    cache = CacheAccess(session_factory=session_factory, collector="rdap", schema_version="1")
    await cache.set(
        compute_cache_key(collector="rdap", schema_version="1", target_normalized="example.com"),
        status=CACHE_STATUS_SUCCESS, response_json={}, normalized_findings_json={}, ttl_seconds=86400,  # not expired
    )

    async with session_factory() as session:
        await purge_all(session)

    async with session_factory() as session:
        result = await inventory(session)
    assert result.total_entries == 0
