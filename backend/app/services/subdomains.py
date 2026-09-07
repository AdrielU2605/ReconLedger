"""UX-07 subdomain workspace: normalized, deduplicated rows restricted to the
assessed registrable domain, aggregated across every collector that
contributed subdomain evidence in a job (today: crt.sh's ct.subdomain kind;
CP6's archive collectors are expected to add more without needing to change
this aggregation's shape - see _EXTRACTORS below).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.models.db import Finding


@dataclass
class SubdomainRow:
    subdomain: str
    source_count: int
    sources: list[str]
    first_seen_at: str | None
    last_seen_at: str | None
    wildcard: bool
    in_scope: bool


@dataclass
class _Accumulator:
    sources: set[str] = field(default_factory=set)
    wildcard: bool = False
    first_seen_at: str | None = None
    last_seen_at: str | None = None


def _extract_from_ct_subdomain(finding: Finding) -> tuple[str, bool, str | None, str | None] | None:
    subdomain = finding.normalized_value_json.get("subdomain")
    if not subdomain:
        return None
    wildcard = bool(finding.normalized_value_json.get("wildcard"))
    first_seen = finding.normalized_value_json.get("not_before_min")
    last_seen = finding.normalized_value_json.get("not_after_max")
    return subdomain, wildcard, first_seen, last_seen


# Extend this as later collectors (CP6's Wayback/Common Crawl) contribute
# subdomain-shaped evidence under their own finding kind.
_EXTRACTORS: dict[str, Callable[[Finding], tuple[str, bool, str | None, str | None] | None]] = {
    "ct.subdomain": _extract_from_ct_subdomain,
}


def aggregate_subdomains(target_normalized: str, findings: list[Finding]) -> list[SubdomainRow]:
    by_subdomain: dict[str, _Accumulator] = {}

    for finding in findings:
        extractor = _EXTRACTORS.get(finding.kind)
        if extractor is None:
            continue
        extracted = extractor(finding)
        if extracted is None:
            continue
        subdomain, wildcard, first_seen, last_seen = extracted

        entry = by_subdomain.setdefault(subdomain, _Accumulator())
        entry.sources.add(finding.collector)
        entry.wildcard = entry.wildcard or wildcard
        if first_seen and (entry.first_seen_at is None or first_seen < entry.first_seen_at):
            entry.first_seen_at = first_seen
        if last_seen and (entry.last_seen_at is None or last_seen > entry.last_seen_at):
            entry.last_seen_at = last_seen

    rows = [
        SubdomainRow(
            subdomain=subdomain,
            source_count=len(entry.sources),
            sources=sorted(entry.sources),
            first_seen_at=entry.first_seen_at,
            last_seen_at=entry.last_seen_at,
            wildcard=entry.wildcard,
            # Every current extractor only accepts names already filtered to
            # the registrable domain at collection time (see crtsh.py's
            # _normalize_name), so this is a defensive re-check, not the
            # primary filter.
            in_scope=(subdomain == target_normalized or subdomain.endswith("." + target_normalized)),
        )
        for subdomain, entry in by_subdomain.items()
    ]
    return sorted((r for r in rows if r.in_scope), key=lambda r: r.subdomain)
