"""PRD 10.3: 'Database migrations create and upgrade a clean SQLite database.'
Exercised here, not just claimed in a README checklist. Also proves the FTS5
virtual table + sync triggers (which Alembic cannot autogenerate) actually work.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.db.base import new_uuid
from app.models.db import Job
from app.models.enums import JobStatus, TargetType


@pytest.mark.asyncio
async def test_migration_creates_all_expected_tables(session_factory) -> None:
    async with session_factory() as session:
        result = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
        tables = {row[0] for row in result.all()}

    for expected in {"jobs", "collector_runs", "findings", "cache_entries", "job_events", "alembic_version"}:
        assert expected in tables


@pytest.mark.asyncio
async def test_a_job_round_trips_with_correct_enum_types(session_factory) -> None:
    job_id = new_uuid()
    async with session_factory() as session:
        async with session.begin():
            session.add(
                Job(
                    id=job_id,
                    target_input="example.com",
                    target_normalized="example.com",
                    target_type=TargetType.DOMAIN,
                    status=JobStatus.QUEUED,
                    attestation_text="I own or am authorized to assess this target.",
                    attestation_version="1.0",
                    attestation_time=datetime.now(timezone.utc),
                    selected_sources_json=["rdap", "dns_doh"],
                )
            )

    async with session_factory() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        # This is the exact bug a plain String column silently allows: without
        # sa.Enum conversion, these would come back as plain str, not enums.
        assert job.target_type is TargetType.DOMAIN
        assert job.status is JobStatus.QUEUED
        assert job.selected_sources_json == ["rdap", "dns_doh"]


@pytest.mark.asyncio
async def test_findings_fts_virtual_table_is_kept_in_sync_by_triggers(session_factory) -> None:
    job_id = new_uuid()
    async with session_factory() as session:
        async with session.begin():
            session.add(
                Job(
                    id=job_id,
                    target_input="example.com",
                    target_normalized="example.com",
                    target_type=TargetType.DOMAIN,
                    status=JobStatus.RUNNING,
                    attestation_text="attestation",
                    attestation_version="1.0",
                    attestation_time=datetime.now(timezone.utc),
                    selected_sources_json=["rdap"],
                )
            )
            await session.flush()
            await session.execute(
                text(
                    "INSERT INTO findings "
                    "(id, job_id, collector, category, kind, title, summary, "
                    " normalized_value_json, raw_evidence_json, source_url, retrieved_at, fingerprint) "
                    "VALUES (:id, :job_id, 'rdap', 'network_footprint', 'rdap.registrar', "
                    " 'Registrar: Example Registrar Inc', 'A very distinctive summary sentence', "
                    " '{}', '{}', 'https://rdap.example/domain/example.com', :retrieved_at, 'fp1')"
                ),
                {"id": new_uuid(), "job_id": job_id, "retrieved_at": datetime.now(timezone.utc).isoformat()},
            )

    async with session_factory() as session:
        result = await session.execute(
            text("SELECT title FROM findings_fts WHERE findings_fts MATCH 'distinctive'")
        )
        rows = result.all()
        assert len(rows) == 1
        assert "Registrar" in rows[0][0]

        # Deleting the finding must remove it from the FTS index too (the
        # 'delete' trigger form), not just leave it stale.
        await session.execute(text("DELETE FROM findings WHERE job_id = :job_id"), {"job_id": job_id})
        await session.commit()
        result = await session.execute(
            text("SELECT title FROM findings_fts WHERE findings_fts MATCH 'distinctive'")
        )
        assert result.all() == []
