"""Pydantic request/response schemas for the REST API (PRD 7.4)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Category, CollectorStatus, Confidence, JobStatus, TargetType


class JobCreateRequest(BaseModel):
    target: str = Field(min_length=1, max_length=512)
    selected_sources: list[str] = Field(min_length=1)
    scope_note: str | None = Field(default=None, max_length=2000)
    attestation_confirmed: bool


class CollectorRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    collector: str
    status: CollectorStatus
    attempt_count: int
    cache_hit: bool
    finding_count: int
    safe_error_code: str | None
    safe_error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None


class JobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    target_input: str
    target_normalized: str
    target_type: TargetType
    status: JobStatus
    selected_sources_json: list[str] = Field(serialization_alias="selected_sources")
    scope_note: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobDetail(JobSummary):
    attestation_text: str
    attestation_version: str
    attestation_time: datetime
    collector_runs: list[CollectorRunRead]


class FindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    collector: str
    category: Category
    kind: str
    title: str
    summary: str
    normalized_value_json: dict[str, Any] = Field(serialization_alias="normalized_value")
    raw_evidence_json: dict[str, Any] = Field(serialization_alias="raw_evidence")
    source_url: str
    provider_observed_at: datetime | None
    retrieved_at: datetime
    confidence: Confidence | None
    fingerprint: str


class SourceRead(BaseModel):
    name: str
    display_name: str
    supported_targets: list[TargetType]
    categories: list[Category]
    release: str
    state: str
    key_help_url: str | None


class DiffFindingRead(BaseModel):
    fingerprint: str
    collector: str
    kind: str
    title: str
    summary: str
    normalized_value: dict[str, Any]


class DiffChangedPair(BaseModel):
    old: DiffFindingRead
    new: DiffFindingRead


class DiffResponse(BaseModel):
    added: list[DiffFindingRead]
    removed: list[DiffFindingRead]
    changed: list[DiffChangedPair]
    unchanged_count: int
    indeterminate: list[DiffFindingRead]
