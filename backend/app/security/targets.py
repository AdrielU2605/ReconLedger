"""Target classification and canonicalization (PRD 4.4, UX-02, 8.2).

This is a security boundary, not just a UX convenience: it is enforced here at
job creation (server-side), independent of whatever the frontend already did.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

from app.models.enums import TargetType
from app.security.network import is_forbidden_address

MAX_RAW_INPUT_LENGTH = 512
MIN_ORGANIZATION_LENGTH = 2
MAX_ORGANIZATION_LENGTH = 120
MAX_DOMAIN_LENGTH = 253
MAX_IPV4_CIDR_PREFIXLEN_SIZE = 16  # "/16 or narrower" -> prefixlen must be >= 16
MAX_IPV6_CIDR_PREFIXLEN_SIZE = 48  # "/48 or narrower" -> prefixlen must be >= 48

_LDH_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class TargetValidationError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ClassifiedTarget:
    target_type: TargetType
    original_input: str
    normalized: str
    assessable: bool = True
    explanation: str | None = None


def _reject_universal_patterns(stripped: str) -> None:
    if "://" in stripped:
        raise TargetValidationError("Input must not include a URL scheme.")
    if "@" in stripped:
        raise TargetValidationError("Input must not include credentials.")
    if "*" in stripped:
        raise TargetValidationError("Wildcard targets are not supported.")


def _classify_cidr_or_reject_path(stripped: str) -> ClassifiedTarget:
    try:
        network = ipaddress.ip_network(stripped, strict=True)
    except ValueError as exc:
        raise TargetValidationError(
            "Input contains a path or is not a valid CIDR network address."
        ) from exc

    if isinstance(network, ipaddress.IPv4Network):
        if network.prefixlen < MAX_IPV4_CIDR_PREFIXLEN_SIZE:
            raise TargetValidationError(
                f"IPv4 CIDR blocks must be /{MAX_IPV4_CIDR_PREFIXLEN_SIZE} or narrower."
            )
    else:
        if network.prefixlen < MAX_IPV6_CIDR_PREFIXLEN_SIZE:
            raise TargetValidationError(
                f"IPv6 CIDR blocks must be /{MAX_IPV6_CIDR_PREFIXLEN_SIZE} or narrower."
            )

    # CIDR ranges are exempt from the private/reserved rejection that applies
    # to single IPs: the fixed verification target 203.0.113.0/24 is
    # IANA-reserved documentation space, and RDAP/RIPEstat queries against a
    # reserved block's real registry data are legitimate.
    return ClassifiedTarget(
        target_type=TargetType.CIDR, original_input=stripped, normalized=str(network)
    )


def _classify_ip(stripped: str, *, allow_private_for_testing: bool) -> ClassifiedTarget | None:
    try:
        address = ipaddress.ip_address(stripped)
    except ValueError:
        return None

    if not allow_private_for_testing:
        reason = is_forbidden_address(address)
        if reason:
            raise TargetValidationError(
                f"{stripped!r} is a {reason} and cannot be used as an assessment target."
            )

    return ClassifiedTarget(target_type=TargetType.IP, original_input=stripped, normalized=str(address))


def _classify_domain(stripped: str) -> ClassifiedTarget | None:
    lowered = stripped.lower().rstrip(".")
    if "." not in lowered:
        return None

    labels = lowered.split(".")
    if any(label == "" for label in labels):
        raise TargetValidationError("Domain contains an empty label.")

    encoded_labels: list[str] = []
    for label in labels:
        try:
            encoded_labels.append(label.encode("idna").decode("ascii"))
        except UnicodeError as exc:
            raise TargetValidationError(f"Domain label {label!r} is not valid.") from exc

    for label in encoded_labels:
        if not _LDH_LABEL_RE.match(label):
            raise TargetValidationError(f"Domain label {label!r} is not valid.")

    canonical = ".".join(encoded_labels)
    if len(canonical) > MAX_DOMAIN_LENGTH:
        raise TargetValidationError("Domain exceeds the maximum length.")

    if len(encoded_labels) < 2:
        raise TargetValidationError("Domain must be a registrable domain (at least two labels).")
    if encoded_labels[-1].isdigit():
        raise TargetValidationError("Domain does not look like a valid registrable domain.")

    return ClassifiedTarget(target_type=TargetType.DOMAIN, original_input=stripped, normalized=canonical)


def _classify_organization(stripped: str) -> ClassifiedTarget:
    if len(stripped) < MIN_ORGANIZATION_LENGTH or len(stripped) > MAX_ORGANIZATION_LENGTH:
        raise TargetValidationError(
            "Input does not look like a domain, IP, or CIDR, and is not a valid "
            f"organization name ({MIN_ORGANIZATION_LENGTH}-{MAX_ORGANIZATION_LENGTH} characters)."
        )
    normalized = " ".join(stripped.split())
    return ClassifiedTarget(
        target_type=TargetType.ORGANIZATION,
        original_input=stripped,
        normalized=normalized,
        assessable=False,
        explanation=(
            "No MVP collector accepts organization targets. Organization search ships in "
            "release 1.1 alongside the organization-capable keyed sources."
        ),
    )


def classify_target(raw_input: str, *, allow_private_ip_for_testing: bool = False) -> ClassifiedTarget:
    """The single server-side entry point for validating and canonicalizing a
    target. Raises TargetValidationError with a user-facing reason on
    anything that fails validation."""
    if len(raw_input) > MAX_RAW_INPUT_LENGTH:
        raise TargetValidationError(
            f"Input exceeds the maximum length of {MAX_RAW_INPUT_LENGTH} characters."
        )
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in raw_input):
        raise TargetValidationError("Input contains control characters.")

    stripped = raw_input.strip()
    if not stripped:
        raise TargetValidationError("Input is empty.")

    if "/" in stripped:
        _reject_universal_patterns(stripped)
        return _classify_cidr_or_reject_path(stripped)

    ip_result = _classify_ip(stripped, allow_private_for_testing=allow_private_ip_for_testing)
    if ip_result is not None:
        return ip_result

    _reject_universal_patterns(stripped)
    if ":" in stripped:
        raise TargetValidationError("Input must not include a port.")

    domain_result = _classify_domain(stripped)
    if domain_result is not None:
        return domain_result

    return _classify_organization(stripped)
