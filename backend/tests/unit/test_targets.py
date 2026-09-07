import pytest

from app.models.enums import TargetType
from app.security.targets import TargetValidationError, classify_target


def test_domain_is_lowercased_and_trailing_dot_stripped() -> None:
    result = classify_target("Example.COM.")
    assert result.target_type == TargetType.DOMAIN
    assert result.normalized == "example.com"
    assert result.assessable


def test_domain_with_unicode_label_is_idna_encoded() -> None:
    result = classify_target("münchen.example")
    assert result.target_type == TargetType.DOMAIN
    assert result.normalized.startswith("xn--")


@pytest.mark.parametrize(
    "raw",
    [
        "http://example.com",
        "example.com/path",
        "user@example.com",
        "*.example.com",
        "example.com:8080",
        "example..com",
        ".example.com",
        "not a domain at all but way too long " + "x" * 500,
    ],
)
def test_invalid_domain_shaped_inputs_are_rejected(raw: str) -> None:
    with pytest.raises(TargetValidationError):
        classify_target(raw)


def test_control_characters_are_rejected() -> None:
    with pytest.raises(TargetValidationError):
        classify_target("example.com\x00")


def test_overlong_input_is_rejected() -> None:
    with pytest.raises(TargetValidationError):
        classify_target("a" * 600)


def test_public_ip_is_classified() -> None:
    result = classify_target("93.184.216.34")
    assert result.target_type == TargetType.IP
    assert result.normalized == "93.184.216.34"


def test_private_ip_is_rejected_by_default() -> None:
    with pytest.raises(TargetValidationError):
        classify_target("10.0.0.5")


def test_private_ip_allowed_in_developer_test_mode() -> None:
    result = classify_target("10.0.0.5", allow_private_ip_for_testing=True)
    assert result.target_type == TargetType.IP
    assert result.normalized == "10.0.0.5"


def test_fixed_verification_cidr_is_accepted_despite_being_documentation_space() -> None:
    """203.0.113.0/24 is the PRD's fixed verification target and is
    IANA-reserved documentation space - CIDR inputs are not subject to the
    private/reserved rejection that applies to single IPs."""
    result = classify_target("203.0.113.0/24")
    assert result.target_type == TargetType.CIDR
    assert result.normalized == "203.0.113.0/24"


def test_cidr_wider_than_slash_16_is_rejected() -> None:
    with pytest.raises(TargetValidationError):
        classify_target("10.0.0.0/8")


def test_ipv6_cidr_wider_than_slash_48_is_rejected() -> None:
    with pytest.raises(TargetValidationError):
        classify_target("2001:db8::/32")


def test_ipv6_cidr_at_slash_48_is_accepted() -> None:
    result = classify_target("2001:db8::/48")
    assert result.target_type == TargetType.CIDR


def test_organization_name_is_classified_but_not_assessable() -> None:
    result = classify_target("Example Corp")
    assert result.target_type == TargetType.ORGANIZATION
    assert result.normalized == "Example Corp"
    assert result.assessable is False
    assert "release 1.1" in result.explanation


def test_organization_name_whitespace_is_collapsed() -> None:
    result = classify_target("  Example   Corp  ")
    assert result.normalized == "Example Corp"


def test_too_short_organization_name_is_rejected() -> None:
    with pytest.raises(TargetValidationError):
        classify_target("E")


def test_dotted_numeric_input_that_is_not_a_valid_ip_is_rejected_as_domain() -> None:
    """Once an input contains a dot and fails IP parsing, a numeric-looking
    TLD is treated as an invalid domain attempt rather than silently
    reinterpreted as an organization name - the user gets a specific reason."""
    with pytest.raises(TargetValidationError):
        classify_target("999.999.999.999")
