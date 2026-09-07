from datetime import datetime, timezone

from app.models.db import Finding
from app.models.enums import Category
from app.services.subdomains import aggregate_subdomains


def _ct_finding(subdomain: str, *, collector="crtsh", wildcard=False, not_before=None, not_after=None) -> Finding:
    return Finding(
        id=f"finding-{subdomain}-{collector}",
        job_id="job-1",
        collector=collector,
        category=Category.NETWORK_FOOTPRINT,
        kind="ct.subdomain",
        title=subdomain,
        summary="...",
        normalized_value_json={
            "subdomain": subdomain,
            "wildcard": wildcard,
            "not_before_min": not_before,
            "not_after_max": not_after,
        },
        raw_evidence_json={},
        source_url="https://crt.sh/",
        retrieved_at=datetime.now(timezone.utc),
        fingerprint=f"fp-{subdomain}",
    )


def test_single_source_subdomain_is_reported() -> None:
    rows = aggregate_subdomains("example.com", [_ct_finding("www.example.com")])
    assert len(rows) == 1
    assert rows[0].subdomain == "www.example.com"
    assert rows[0].source_count == 1
    assert rows[0].sources == ["crtsh"]
    assert rows[0].in_scope is True


def test_same_subdomain_from_two_collectors_is_merged() -> None:
    findings = [_ct_finding("www.example.com", collector="crtsh"), _ct_finding("www.example.com", collector="wayback")]
    rows = aggregate_subdomains("example.com", findings)
    assert len(rows) == 1
    assert rows[0].source_count == 2
    assert rows[0].sources == ["crtsh", "wayback"]


def test_out_of_scope_name_is_excluded() -> None:
    """A defensive re-check: even though collectors are expected to only
    surface in-scope names, the aggregation itself never trusts that."""
    rows = aggregate_subdomains("example.com", [_ct_finding("www.not-example.com")])
    assert rows == []


def test_wildcard_flag_is_true_if_any_contributing_finding_says_so() -> None:
    findings = [
        _ct_finding("www.example.com", collector="crtsh", wildcard=False),
        _ct_finding("www.example.com", collector="wayback", wildcard=True),
    ]
    rows = aggregate_subdomains("example.com", findings)
    assert rows[0].wildcard is True


def test_first_and_last_seen_take_the_widest_observed_range() -> None:
    findings = [
        _ct_finding("www.example.com", collector="crtsh", not_before="2020-01-01", not_after="2021-01-01"),
        _ct_finding("www.example.com", collector="wayback", not_before="2019-06-01", not_after="2022-06-01"),
    ]
    rows = aggregate_subdomains("example.com", findings)
    assert rows[0].first_seen_at == "2019-06-01"
    assert rows[0].last_seen_at == "2022-06-01"


def test_unrelated_finding_kinds_are_ignored() -> None:
    other = Finding(
        id="f1", job_id="job-1", collector="rdap", category=Category.NETWORK_FOOTPRINT, kind="rdap.registration",
        title="x", summary="x", normalized_value_json={}, raw_evidence_json={}, source_url="https://rdap.example/",
        retrieved_at=datetime.now(timezone.utc), fingerprint="fp-x",
    )
    assert aggregate_subdomains("example.com", [other]) == []


def test_rows_are_sorted_alphabetically() -> None:
    rows = aggregate_subdomains("example.com", [_ct_finding("zeta.example.com"), _ct_finding("alpha.example.com")])
    assert [r.subdomain for r in rows] == ["alpha.example.com", "zeta.example.com"]
