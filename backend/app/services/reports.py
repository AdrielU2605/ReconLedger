"""FR-11: deterministic Markdown and JSON exports, generated entirely from
persisted evidence (no provider calls). CSV subdomain export is built
alongside the subdomain workspace itself (CP5).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from app.models.db import CollectorRun, Finding, Job
from app.models.enums import Category

EXPORT_SCHEMA_VERSION = "1"
SUMMARY_MODE_ROWS_PER_CATEGORY = 20

MarkdownMode = Literal["summary", "full"]


@dataclass(frozen=True)
class ExportBundle:
    job: Job
    collector_runs: list[CollectorRun]
    findings: list[Finding]


def build_json_export(bundle: ExportBundle) -> dict[str, Any]:
    job = bundle.job
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "job": {
            "id": job.id,
            "target_input": job.target_input,
            "target_normalized": job.target_normalized,
            "target_type": job.target_type.value,
            "status": job.status.value,
            "scope_note": job.scope_note,
            "attestation_text": job.attestation_text,
            "attestation_version": job.attestation_version,
            "attestation_time": job.attestation_time.isoformat(),
            "selected_sources": job.selected_sources_json,
            "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        },
        "collector_runs": [
            {
                "collector": run.collector,
                "status": run.status.value,
                "attempt_count": run.attempt_count,
                "cache_hit": run.cache_hit,
                "finding_count": run.finding_count,
                "safe_error_code": run.safe_error_code,
                "safe_error_message": run.safe_error_message,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            }
            for run in bundle.collector_runs
        ],
        "findings": [
            {
                "id": f.id,
                "collector": f.collector,
                "category": f.category.value,
                "kind": f.kind,
                "title": f.title,
                "summary": f.summary,
                "normalized_value": f.normalized_value_json,
                "raw_evidence": f.raw_evidence_json,
                "source_url": f.source_url,
                "provider_observed_at": f.provider_observed_at.isoformat() if f.provider_observed_at else None,
                "retrieved_at": f.retrieved_at.isoformat(),
                "confidence": f.confidence.value if f.confidence else None,
                "fingerprint": f.fingerprint,
            }
            for f in bundle.findings
        ],
    }


def _markdown_escape(text: str) -> str:
    # Prevents evidence text from breaking report structure (8.2): neutralize
    # characters that would open a new Markdown block or fence.
    return text.replace("|", "\\|").replace("`", "'").replace("\n", " ").strip()


def build_markdown_export(bundle: ExportBundle, *, mode: MarkdownMode = "full") -> str:
    job = bundle.job
    lines: list[str] = []
    lines.append(f"# ReconLedger evidence report - {job.target_normalized}")
    lines.append("")
    lines.append(f"- **Target:** {job.target_normalized} ({job.target_type.value})")
    if job.scope_note:
        lines.append(f"- **Scope note:** {_markdown_escape(job.scope_note)}")
    lines.append(f"- **Authorization attestation:** {_markdown_escape(job.attestation_text)}")
    lines.append(f"- **Attestation time (UTC):** {job.attestation_time.isoformat()}")
    lines.append(f"- **Job status:** {job.status.value}")
    lines.append(
        "- **Methodology and limitations:** All evidence below was collected passively from "
        "allowlisted third-party providers. ReconLedger never contacted the assessed target "
        "directly. A source marked failed or skipped means that source produced no evidence for "
        "this run - it is not evidence of absence."
    )
    lines.append("")

    lines.append("## Source status")
    lines.append("")
    lines.append("| Collector | Status | Findings | Reason |")
    lines.append("|---|---|---|---|")
    for run in bundle.collector_runs:
        reason = _markdown_escape(run.safe_error_message) if run.safe_error_message else ""
        lines.append(f"| {run.collector} | {run.status.value} | {run.finding_count} | {reason} |")
    lines.append("")

    lines.append("## Findings by category")
    for category in Category:
        category_findings = [f for f in bundle.findings if f.category == category]
        lines.append("")
        lines.append(f"### {category.value.replace('_', ' ').title()}")
        if not category_findings:
            lines.append("")
            lines.append("_No findings in this category for this job._")
            continue
        shown = category_findings[:SUMMARY_MODE_ROWS_PER_CATEGORY] if mode == "summary" else category_findings
        lines.append("")
        for finding in shown:
            confidence_note = f" (confidence: {finding.confidence.value})" if finding.confidence else ""
            lines.append(
                f"- **{_markdown_escape(finding.title)}**{confidence_note} - "
                f"{_markdown_escape(finding.summary)} "
                f"[source]({finding.source_url}) - retrieved {finding.retrieved_at.isoformat()}"
            )
        if mode == "summary" and len(category_findings) > SUMMARY_MODE_ROWS_PER_CATEGORY:
            remaining = len(category_findings) - SUMMARY_MODE_ROWS_PER_CATEGORY
            lines.append("")
            lines.append(f"_...and {remaining} more. See the JSON export for the complete record._")

    lines.append("")
    lines.append(f"_Report generated {datetime.now(timezone.utc).isoformat()} by ReconLedger._")
    return "\n".join(lines)
