from app.services.csv_export import build_subdomains_csv
from app.services.subdomains import SubdomainRow


def _row(**overrides) -> SubdomainRow:
    defaults = dict(
        subdomain="www.example.com", source_count=1, sources=["crtsh"],
        first_seen_at="2020-01-01", last_seen_at="2021-01-01", wildcard=False, in_scope=True,
    )
    defaults.update(overrides)
    return SubdomainRow(**defaults)


def test_header_row_is_present() -> None:
    csv_text = build_subdomains_csv([])
    assert csv_text.strip() == "subdomain,source_count,sources,first_seen_at,last_seen_at,wildcard,in_scope"


def test_normal_row_round_trips_correctly() -> None:
    csv_text = build_subdomains_csv([_row()])
    lines = csv_text.strip().splitlines()
    assert lines[1] == "www.example.com,1,crtsh,2020-01-01,2021-01-01,False,True".replace("False", "false").replace("True", "true")


def test_formula_looking_subdomain_is_neutralized() -> None:
    csv_text = build_subdomains_csv([_row(subdomain="=cmd|'/c calc'!A1.example.com")])
    lines = csv_text.strip().splitlines()
    assert lines[1].startswith("'=") or lines[1].startswith('"\'=')  # csv module may quote it


def test_plus_minus_at_and_tab_prefixes_are_all_neutralized() -> None:
    for dangerous in ("+1+1", "-1+1", "@SUM(1,1)", "\tsneaky"):
        csv_text = build_subdomains_csv([_row(subdomain=f"{dangerous}.example.com")])
        first_field = csv_text.strip().splitlines()[1].split(",")[0].strip('"')
        assert first_field.startswith("'")


def test_sources_are_semicolon_joined_and_also_sanitized() -> None:
    csv_text = build_subdomains_csv([_row(sources=["=evil", "crtsh"])])
    assert "'=evil;crtsh" in csv_text


def test_multiple_rows_preserve_order() -> None:
    csv_text = build_subdomains_csv([_row(subdomain="a.example.com"), _row(subdomain="b.example.com")])
    lines = csv_text.strip().splitlines()
    assert lines[1].startswith("a.example.com")
    assert lines[2].startswith("b.example.com")
