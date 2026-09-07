"""Evidence-aware diff (PRD UX-09, 12.2).

Core principle: unknown is not absent. A source that failed or was skipped in
either job can never justify a "removed" result - that would let the app
claim something disappeared when it simply failed to look. Those cases are
"indeterminate" instead. "Added" is not given the same treatment: reporting
new evidence you now have is not the dangerous claim; falsely reporting that
something is gone is.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import CollectorRun, Finding, Job
from app.models.enums import CollectorStatus


class JobNotFoundError(ValueError):
    def __init__(self, job_id: str) -> None:
        super().__init__(f"Job {job_id!r} does not exist.")


class DiffTargetMismatchError(ValueError):
    def __init__(self, old_target: str, new_target: str) -> None:
        super().__init__(
            f"Jobs with different canonical targets cannot be compared "
            f"({old_target!r} vs {new_target!r})."
        )


@dataclass(frozen=True)
class DiffFinding:
    fingerprint: str
    collector: str
    kind: str
    title: str
    summary: str
    normalized_value: dict[str, Any]


@dataclass(frozen=True)
class DiffResult:
    added: list[DiffFinding]
    removed: list[DiffFinding]
    changed: list[tuple[DiffFinding, DiffFinding]]
    unchanged_count: int
    indeterminate: list[DiffFinding]


def _to_diff_finding(finding: Finding) -> DiffFinding:
    return DiffFinding(
        fingerprint=finding.fingerprint,
        collector=finding.collector,
        kind=finding.kind,
        title=finding.title,
        summary=finding.summary,
        normalized_value=finding.normalized_value_json,
    )


def compute_diff(
    *,
    old_target_normalized: str,
    new_target_normalized: str,
    old_findings: list[Finding],
    new_findings: list[Finding],
    old_collector_statuses: dict[str, CollectorStatus],
    new_collector_statuses: dict[str, CollectorStatus],
) -> DiffResult:
    if old_target_normalized != new_target_normalized:
        raise DiffTargetMismatchError(old_target_normalized, new_target_normalized)

    old_by_fp = {f.fingerprint: _to_diff_finding(f) for f in old_findings}
    new_by_fp = {f.fingerprint: _to_diff_finding(f) for f in new_findings}

    added = [new_by_fp[fp] for fp in new_by_fp.keys() - old_by_fp.keys()]

    removed: list[DiffFinding] = []
    indeterminate: list[DiffFinding] = []
    for fp in old_by_fp.keys() - new_by_fp.keys():
        old_finding = old_by_fp[fp]
        collector = old_finding.collector
        completed_in_both = (
            old_collector_statuses.get(collector) == CollectorStatus.DONE
            and new_collector_statuses.get(collector) == CollectorStatus.DONE
        )
        (removed if completed_in_both else indeterminate).append(old_finding)

    changed: list[tuple[DiffFinding, DiffFinding]] = []
    unchanged_count = 0
    for fp in old_by_fp.keys() & new_by_fp.keys():
        old_finding, new_finding = old_by_fp[fp], new_by_fp[fp]
        if old_finding.normalized_value == new_finding.normalized_value:
            unchanged_count += 1
        else:
            changed.append((old_finding, new_finding))

    return DiffResult(added=added, removed=removed, changed=changed, unchanged_count=unchanged_count, indeterminate=indeterminate)


async def diff_jobs(session: AsyncSession, *, new_job_id: str, old_job_id: str) -> DiffResult:
    new_job = await session.get(Job, new_job_id)
    if new_job is None:
        raise JobNotFoundError(new_job_id)
    old_job = await session.get(Job, old_job_id)
    if old_job is None:
        raise JobNotFoundError(old_job_id)
    if old_job.target_normalized != new_job.target_normalized:
        raise DiffTargetMismatchError(old_job.target_normalized, new_job.target_normalized)

    async def _collector_statuses(job_id: str) -> dict[str, CollectorStatus]:
        result = await session.execute(select(CollectorRun.collector, CollectorRun.status).where(CollectorRun.job_id == job_id))
        return dict(result.tuples().all())

    async def _findings(job_id: str) -> list[Finding]:
        result = await session.execute(select(Finding).where(Finding.job_id == job_id))
        return list(result.scalars().all())

    old_statuses, new_statuses = await _collector_statuses(old_job_id), await _collector_statuses(new_job_id)
    old_findings, new_findings = await _findings(old_job_id), await _findings(new_job_id)

    return compute_diff(
        old_target_normalized=old_job.target_normalized,
        new_target_normalized=new_job.target_normalized,
        old_findings=old_findings,
        new_findings=new_findings,
        old_collector_statuses=old_statuses,
        new_collector_statuses=new_statuses,
    )
