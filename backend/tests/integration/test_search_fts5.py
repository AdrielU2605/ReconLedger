"""UX-08 global search, backed by the findings_fts FTS5 projection migrated
in 0001_initial. Exercises the real trigger-synced virtual table, not a mock."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.base import utcnow
from app.models.db import Finding, Job
from app.models.enums import Category, JobStatus, TargetType
from app.services.search import find_matching_finding_ids, fts5_phrase_query


async def _make_job(session_factory) -> str:
    async with session_factory() as session:
        async with session.begin():
            job = Job(
                target_input="example.com",
                target_normalized="example.com",
                target_type=TargetType.DOMAIN,
                status=JobStatus.COMPLETED,
                attestation_text="...",
                attestation_version="1",
                attestation_time=utcnow(),
                selected_sources_json=["rdap"],
                created_at=utcnow(),
            )
            session.add(job)
        await session.refresh(job)
        return job.id


async def _add_finding(session_factory, job_id: str, **overrides) -> None:
    defaults = dict(
        job_id=job_id,
        collector="rdap",
        category=Category.NETWORK_FOOTPRINT,
        kind="rdap.registration",
        title="RDAP record for example.com",
        summary="Registrar: Example Registrar Inc.",
        normalized_value_json={},
        raw_evidence_json={"nameserver": "ns1.example-registrar.test"},
        source_url="https://rdap.example/domain/example.com",
        retrieved_at=datetime.now(timezone.utc),
        fingerprint="fp-1",
    )
    defaults.update(overrides)
    async with session_factory() as session:
        async with session.begin():
            session.add(Finding(**defaults))


def test_fts5_phrase_query_escapes_embedded_quotes() -> None:
    assert fts5_phrase_query('say "hi"') == '"say ""hi"""'


@pytest.mark.asyncio
async def test_search_matches_on_title_and_summary(session_factory) -> None:
    job_id = await _make_job(session_factory)
    await _add_finding(session_factory, job_id, fingerprint="fp-1")

    async with session_factory() as session:
        matches = await find_matching_finding_ids(session, job_id=job_id, query="Example Registrar")
    assert len(matches) == 1


@pytest.mark.asyncio
async def test_search_matches_raw_evidence_text(session_factory) -> None:
    job_id = await _make_job(session_factory)
    await _add_finding(session_factory, job_id, fingerprint="fp-1")

    async with session_factory() as session:
        matches = await find_matching_finding_ids(session, job_id=job_id, query="ns1.example-registrar.test")
    assert len(matches) == 1


@pytest.mark.asyncio
async def test_search_is_scoped_to_the_given_job(session_factory) -> None:
    job_a = await _make_job(session_factory)
    job_b = await _make_job(session_factory)
    await _add_finding(session_factory, job_a, fingerprint="fp-a")
    await _add_finding(session_factory, job_b, fingerprint="fp-b")

    async with session_factory() as session:
        matches = await find_matching_finding_ids(session, job_id=job_a, query="Example Registrar")
    assert len(matches) == 1


@pytest.mark.asyncio
async def test_no_match_returns_empty_list(session_factory) -> None:
    job_id = await _make_job(session_factory)
    await _add_finding(session_factory, job_id, fingerprint="fp-1")

    async with session_factory() as session:
        matches = await find_matching_finding_ids(session, job_id=job_id, query="nothing-like-this-exists")
    assert matches == []


@pytest.mark.asyncio
async def test_special_characters_do_not_raise_a_syntax_error(session_factory) -> None:
    """A hyphen, quote, or asterisk in free-text input must never reach FTS5
    as unescaped query syntax."""
    job_id = await _make_job(session_factory)
    await _add_finding(session_factory, job_id, fingerprint="fp-1")

    async with session_factory() as session:
        for tricky_query in ['weird-input', 'quote"inside', "wild*card", "col:umn"]:
            matches = await find_matching_finding_ids(session, job_id=job_id, query=tricky_query)
            assert matches == []  # no crash, just no match


@pytest.mark.asyncio
async def test_deleted_finding_is_removed_from_the_fts_index(session_factory) -> None:
    """Proves the AFTER DELETE trigger (0001_initial) actually keeps the FTS5
    projection in sync, not just the AFTER INSERT one."""
    job_id = await _make_job(session_factory)
    await _add_finding(session_factory, job_id, fingerprint="fp-1")

    async with session_factory() as session:
        assert len(await find_matching_finding_ids(session, job_id=job_id, query="Example Registrar")) == 1

    async with session_factory() as session:
        async with session.begin():
            result = await session.execute(select(Finding).where(Finding.job_id == job_id))
            for finding in result.scalars().all():
                await session.delete(finding)

    async with session_factory() as session:
        assert await find_matching_finding_ids(session, job_id=job_id, query="Example Registrar") == []
