"""SQLAlchemy 2 async ORM models (PRD 7.5 Persistence model).

Schema changes are made only through Alembic migrations (backend/alembic/versions);
this module is never used with Base.metadata.create_all() outside of throwaway
test fixtures that then run the real migrations anyway to exercise them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeEngine

from app.db.base import Base, new_uuid, utcnow
from app.models.enums import Category, CollectorStatus, Confidence, JobStatus, TargetType


def _enum_column(enum_cls: type, length: int) -> TypeEngine[Any]:
    """A SQLAlchemy Enum stored as plain text (no DB-level CHECK constraint,
    so it stays a trivial VARCHAR for Alembic/SQLite batch-mode purposes) that
    still converts to/from the real Python enum on every read and write -
    unlike a bare String column, which silently hands back a plain str."""
    return SAEnum(
        enum_cls,
        native_enum=False,
        create_constraint=False,
        length=length,
        values_callable=lambda e: [member.value for member in e],
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    target_input: Mapped[str] = mapped_column(String(255))
    target_normalized: Mapped[str] = mapped_column(String(255), index=True)
    target_type: Mapped[TargetType] = mapped_column(_enum_column(TargetType, 20))
    status: Mapped[JobStatus] = mapped_column(_enum_column(JobStatus, 30), default=JobStatus.QUEUED, index=True)
    scope_note: Mapped[str | None] = mapped_column(Text, default=None)
    attestation_text: Mapped[str] = mapped_column(Text)
    attestation_version: Mapped[str] = mapped_column(String(20))
    attestation_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    selected_sources_json: Mapped[list[str]] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    collector_runs: Mapped[list["CollectorRun"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    events: Mapped[list["JobEvent"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class CollectorRun(Base):
    __tablename__ = "collector_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    collector: Mapped[str] = mapped_column(String(60))
    status: Mapped[CollectorStatus] = mapped_column(_enum_column(CollectorStatus, 30), default=CollectorStatus.QUEUED)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    finding_count: Mapped[int] = mapped_column(Integer, default=0)
    safe_error_code: Mapped[str | None] = mapped_column(String(60), default=None)
    safe_error_message: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    job: Mapped[Job] = relationship(back_populates="collector_runs")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    collector: Mapped[str] = mapped_column(String(60), index=True)
    category: Mapped[Category] = mapped_column(_enum_column(Category, 30), index=True)
    kind: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text)
    normalized_value_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    raw_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_url: Mapped[str] = mapped_column(String(2048))
    provider_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confidence: Mapped[Confidence | None] = mapped_column(_enum_column(Confidence, 10), default=None)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)

    job: Mapped[Job] = relationship(back_populates="findings")


class CacheEntry(Base):
    __tablename__ = "cache_entries"

    cache_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    collector: Mapped[str] = mapped_column(String(60), index=True)
    schema_version: Mapped[str] = mapped_column(String(20))
    credential_scope_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    status: Mapped[str] = mapped_column(String(20))
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    normalized_findings_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    etag: Mapped[str | None] = mapped_column(String(255), default=None)
    last_modified: Mapped[str | None] = mapped_column(String(255), default=None)


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    collector: Mapped[str | None] = mapped_column(String(60), default=None)
    event_type: Mapped[str] = mapped_column(String(40))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(back_populates="events")
