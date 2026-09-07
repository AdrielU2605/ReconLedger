import pytest

from app.models.db import Finding
from app.models.enums import CollectorStatus
from app.services.diff import DiffTargetMismatchError, compute_diff


def _finding(fingerprint: str, collector: str = "rdap", value: dict | None = None) -> Finding:
    return Finding(
        fingerprint=fingerprint,
        collector=collector,
        kind="rdap.registrar",
        title="Registrar",
        summary="summary",
        normalized_value_json=value or {"registrar": "Example Registrar"},
    )


def test_target_mismatch_is_rejected() -> None:
    with pytest.raises(DiffTargetMismatchError):
        compute_diff(
            old_target_normalized="example.com",
            new_target_normalized="other.example",
            old_findings=[],
            new_findings=[],
            old_collector_statuses={},
            new_collector_statuses={},
        )


def test_new_finding_is_added() -> None:
    result = compute_diff(
        old_target_normalized="example.com",
        new_target_normalized="example.com",
        old_findings=[],
        new_findings=[_finding("fp1")],
        old_collector_statuses={},
        new_collector_statuses={"rdap": CollectorStatus.DONE},
    )
    assert [f.fingerprint for f in result.added] == ["fp1"]
    assert result.removed == []
    assert result.indeterminate == []


def test_added_is_reported_even_if_the_source_never_ran_before() -> None:
    """Unlike removals, an added finding is not downgraded to indeterminate
    just because the collector didn't run in the old job - it's still true
    that we have this evidence now and didn't before."""
    result = compute_diff(
        old_target_normalized="example.com",
        new_target_normalized="example.com",
        old_findings=[],
        new_findings=[_finding("fp1")],
        old_collector_statuses={},  # rdap never ran in the old job
        new_collector_statuses={"rdap": CollectorStatus.DONE},
    )
    assert [f.fingerprint for f in result.added] == ["fp1"]


def test_missing_finding_completed_in_both_jobs_is_removed() -> None:
    result = compute_diff(
        old_target_normalized="example.com",
        new_target_normalized="example.com",
        old_findings=[_finding("fp1")],
        new_findings=[],
        old_collector_statuses={"rdap": CollectorStatus.DONE},
        new_collector_statuses={"rdap": CollectorStatus.DONE},
    )
    assert [f.fingerprint for f in result.removed] == ["fp1"]
    assert result.indeterminate == []


@pytest.mark.parametrize(
    "old_status,new_status",
    [
        (CollectorStatus.FAILED, CollectorStatus.DONE),
        (CollectorStatus.DONE, CollectorStatus.SKIPPED_NO_KEY),
        (CollectorStatus.DONE, CollectorStatus.NOT_APPLICABLE),
    ],
)
def test_missing_finding_is_indeterminate_when_source_did_not_complete_in_both(old_status, new_status) -> None:
    result = compute_diff(
        old_target_normalized="example.com",
        new_target_normalized="example.com",
        old_findings=[_finding("fp1")],
        new_findings=[],
        old_collector_statuses={"rdap": old_status},
        new_collector_statuses={"rdap": new_status},
    )
    assert result.removed == []
    assert [f.fingerprint for f in result.indeterminate] == ["fp1"]


def test_unchanged_finding_is_counted_not_listed() -> None:
    result = compute_diff(
        old_target_normalized="example.com",
        new_target_normalized="example.com",
        old_findings=[_finding("fp1", value={"a": 1})],
        new_findings=[_finding("fp1", value={"a": 1})],
        old_collector_statuses={"rdap": CollectorStatus.DONE},
        new_collector_statuses={"rdap": CollectorStatus.DONE},
    )
    assert result.unchanged_count == 1
    assert result.changed == []


def test_changed_value_is_reported_as_changed_pair() -> None:
    result = compute_diff(
        old_target_normalized="example.com",
        new_target_normalized="example.com",
        old_findings=[_finding("fp1", value={"a": 1})],
        new_findings=[_finding("fp1", value={"a": 2})],
        old_collector_statuses={"rdap": CollectorStatus.DONE},
        new_collector_statuses={"rdap": CollectorStatus.DONE},
    )
    assert len(result.changed) == 1
    old_f, new_f = result.changed[0]
    assert old_f.normalized_value == {"a": 1}
    assert new_f.normalized_value == {"a": 2}
