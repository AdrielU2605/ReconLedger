"""The collector plug-in contract (PRD FR-02, 7.6).

Every data source is an isolated module implementing this same typed
contract. A collector never receives httpx.AsyncClient directly - only the
OutboundGateway passed on its context - and it returns plain, not-yet-persisted
CollectedFinding records; the job runner is responsible for turning those into
Finding rows with a job_id.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.models.enums import Category, Confidence, TargetType
from app.security.gateway import OutboundGateway
from app.security.targets import ClassifiedTarget


@dataclass(frozen=True)
class RatePolicy:
    requests_per_period: float
    period_seconds: float
    burst: int
    concurrency: int


@dataclass(frozen=True)
class CachePolicy:
    positive_ttl_seconds: float
    negative_ttl_seconds: float
    schema_version: str


@dataclass(frozen=True)
class CollectorMetadata:
    name: str
    display_name: str
    supported_targets: frozenset[TargetType]
    categories: frozenset[Category]
    required_credentials: tuple[str, ...]
    provider_hosts: frozenset[str]
    key_help_url: str | None
    rate_policy: RatePolicy
    cache_policy: CachePolicy
    request_timeout_seconds: float | None = None  # None -> settings default
    test_only: bool = False
    """True only for fixtures used by the test suite itself (e.g. a no-op
    collector used to exercise the job runner). See collectors/registry.py:
    a test_only collector cannot be registered on the production registry."""


@dataclass(frozen=True)
class CollectedFinding:
    """A finding as a collector produces it, before the runner assigns it a
    job_id and persists it (FR-06).

    `fingerprint` is computed by the collector itself (via
    app.services.fingerprint.compute_fingerprint) because only the collector
    knows, for its own `kind`, which fields form the stable identity key and
    which are mutable attributes that should be allowed to change between
    runs without registering as a false add/remove in a diff.
    """

    category: Category
    kind: str
    title: str
    summary: str
    normalized_value: dict[str, Any]
    raw_evidence: dict[str, Any]
    source_url: str
    retrieved_at: datetime
    fingerprint: str
    provider_observed_at: datetime | None = None
    confidence: Confidence | None = None


@dataclass
class CollectorContext:
    job_id: str
    target: ClassifiedTarget
    scope_note: str | None
    gateway: OutboundGateway
    cancellation: asyncio.Event
    job_deadline_monotonic: float
    collector_budget_seconds: float


class Collector(Protocol):
    """The static-and-instance shape every collector module must provide."""

    metadata: CollectorMetadata

    async def run(self, context: CollectorContext) -> list[CollectedFinding]: ...
