"""Shared cache-serialization glue for collectors (FR-05).

Every collector's cache entry stores the same generic shape - a list of
serialized CollectedFinding records - so this lives here once instead of
being reinvented per collector.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.collectors.base import CollectedFinding, CollectorContext
from app.models.enums import Category, Confidence
from app.services.cache import CacheAccess


def serialize_finding(finding: CollectedFinding) -> dict[str, Any]:
    return {
        "category": finding.category.value,
        "kind": finding.kind,
        "title": finding.title,
        "summary": finding.summary,
        "normalized_value": finding.normalized_value,
        "raw_evidence": finding.raw_evidence,
        "source_url": finding.source_url,
        "retrieved_at": finding.retrieved_at.isoformat(),
        "fingerprint": finding.fingerprint,
        "provider_observed_at": finding.provider_observed_at.isoformat() if finding.provider_observed_at else None,
        "confidence": finding.confidence.value if finding.confidence else None,
    }


def deserialize_finding(data: dict[str, Any]) -> CollectedFinding:
    return CollectedFinding(
        category=Category(data["category"]),
        kind=data["kind"],
        title=data["title"],
        summary=data["summary"],
        normalized_value=data["normalized_value"],
        raw_evidence=data["raw_evidence"],
        source_url=data["source_url"],
        retrieved_at=datetime.fromisoformat(data["retrieved_at"]),
        fingerprint=data["fingerprint"],
        provider_observed_at=(
            datetime.fromisoformat(data["provider_observed_at"]) if data.get("provider_observed_at") else None
        ),
        confidence=Confidence(data["confidence"]) if data.get("confidence") else None,
    )


async def get_cached_findings(context: CollectorContext, cache_key: str) -> list[CollectedFinding] | None:
    """Returns None on a miss (including an expired entry). On a hit, marks
    context.cache_hit so the runner records it on the CollectorRun, and
    returns the findings exactly as originally retrieved - including their
    original retrieved_at, since serving from cache is not a fresh retrieval."""
    entry = await context.cache.get(cache_key)
    if entry is None:
        return None
    context.cache_hit = True
    return [deserialize_finding(d) for d in entry.normalized_findings_json.get("findings", [])]


async def store_findings_in_cache(
    cache: CacheAccess,
    cache_key: str,
    findings: list[CollectedFinding],
    *,
    status: str,
    response_json: dict[str, Any],
    ttl_seconds: float,
) -> None:
    await cache.set(
        cache_key,
        status=status,
        response_json=response_json,
        normalized_findings_json={"findings": [serialize_finding(f) for f in findings]},
        ttl_seconds=ttl_seconds,
    )
