from datetime import datetime, timezone

from app.models.db import CollectorRun, Finding, Job
from app.models.enums import Category, CollectorStatus, JobStatus, TargetType
from app.services.reports import (
    EXPORT_SCHEMA_VERSION,
    SUMMARY_MODE_ROWS_PER_CATEGORY,
    ExportBundle,
    build_json_export,
    build_markdown_export,
)


def _job(**overrides) -> Job:
    defaults = dict(
        id="job-1",
        target_input="example.com",
        target_normalized="example.com",
        target_type=TargetType.DOMAIN,
        status=JobStatus.COMPLETED,
        scope_note="Authorized pentest engagement #42",
        attestation_text="I own or am authorized to assess this target.",
        attestation_version="1.0",
        attestation_time=datetime.now(timezone.utc),
        selected_sources_json=["rdap"],
        created_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Job(**defaults)


def _run(**overrides) -> CollectorRun:
    defaults = dict(
        id="run-1", job_id="job-1", collector="rdap", status=CollectorStatus.DONE,
        attempt_count=1, cache_hit=False, finding_count=1, safe_error_code=None,
        safe_error_message=None, started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return CollectorRun(**defaults)


def _finding(**overrides) -> Finding:
    defaults = dict(
        id="f-1", job_id="job-1", collector="rdap", category=Category.NETWORK_FOOTPRINT,
        kind="rdap.registrar", title="Registrar: Example Registrar Inc",
        summary="Registered via Example Registrar", normalized_value_json={"registrar": "Example"},
        raw_evidence_json={"raw": True}, source_url="https://rdap.example/domain/example.com",
        provider_observed_at=None, retrieved_at=datetime.now(timezone.utc), confidence=None,
        fingerprint="fp-1",
    )
    defaults.update(overrides)
    return Finding(**defaults)


def test_json_export_has_schema_version_and_all_sections() -> None:
    bundle = ExportBundle(job=_job(), collector_runs=[_run()], findings=[_finding()])
    export = build_json_export(bundle)

    assert export["schema_version"] == EXPORT_SCHEMA_VERSION
    assert export["job"]["target_normalized"] == "example.com"
    assert export["job"]["scope_note"] == "Authorized pentest engagement #42"
    assert len(export["collector_runs"]) == 1
    assert len(export["findings"]) == 1
    assert export["findings"][0]["fingerprint"] == "fp-1"


def test_markdown_export_includes_attestation_scope_and_source_status() -> None:
    bundle = ExportBundle(job=_job(), collector_runs=[_run()], findings=[_finding()])
    markdown = build_markdown_export(bundle, mode="full")

    assert "example.com" in markdown
    assert "Authorized pentest engagement #42" in markdown
    assert "I own or am authorized to assess this target." in markdown
    assert "## Source status" in markdown
    assert "rdap" in markdown
    assert "## Findings by category" in markdown
    assert "Registrar: Example Registrar Inc" in markdown


def test_markdown_export_reports_empty_categories_explicitly() -> None:
    bundle = ExportBundle(job=_job(), collector_runs=[_run()], findings=[_finding()])
    markdown = build_markdown_export(bundle, mode="full")
    assert "_No findings in this category for this job._" in markdown  # human_layer, leaked_data etc.


def test_summary_mode_caps_rows_and_points_to_json() -> None:
    many_findings = [
        _finding(id=f"f-{i}", fingerprint=f"fp-{i}", title=f"Finding {i}")
        for i in range(SUMMARY_MODE_ROWS_PER_CATEGORY + 5)
    ]
    bundle = ExportBundle(job=_job(), collector_runs=[_run()], findings=many_findings)

    summary = build_markdown_export(bundle, mode="summary")
    full = build_markdown_export(bundle, mode="full")

    assert "Finding 0" in summary
    assert f"Finding {SUMMARY_MODE_ROWS_PER_CATEGORY + 4}" not in summary
    assert "...and 5 more. See the JSON export for the complete record." in summary
    assert f"Finding {SUMMARY_MODE_ROWS_PER_CATEGORY + 4}" in full


def test_markdown_escaping_neutralizes_structure_breaking_characters() -> None:
    finding = _finding(
        title="Weird | title with `code` and\nnewline",
        summary="summary",
    )
    bundle = ExportBundle(job=_job(), collector_runs=[_run()], findings=[finding])
    markdown = build_markdown_export(bundle)

    assert "| title" not in markdown or "\\|" in markdown
    assert "`code`" not in markdown
    assert "with 'code' and newline" in markdown
