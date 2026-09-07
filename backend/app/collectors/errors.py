"""The per-collector error taxonomy (PRD FR-02, 12.2).

Distinct from app.security.errors (which covers the outbound gateway's own
policy failures): these are the outcomes a collector's run() is allowed to
raise, and every one of them maps directly to a CollectorRun.status plus a
safe_error_code/safe_error_message pair - never a bare, unclassified
exception. Defined before the first real collector (CP3) so every collector
built from here on reports failure the same way.
"""
from __future__ import annotations

from app.models.enums import CollectorStatus
from app.security.errors import (
    BlockedDestinationError,
    DisallowedHostError,
    GatewayError,
    MalformedResponseError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ResponseTooLargeError,
)


class CollectorError(Exception):
    """Base class for every typed failure a collector's run() may raise."""

    safe_error_code = "collector_error"
    # The CollectorRun.status a run() raising this error should be recorded as.
    resulting_status = CollectorStatus.FAILED

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.safe_error_message = message


class TargetNotApplicableError(CollectorError):
    safe_error_code = "not_applicable"
    resulting_status = CollectorStatus.NOT_APPLICABLE

    def __init__(self, collector: str, target_type: str) -> None:
        super().__init__(f"{collector} does not support target type {target_type!r}.")


class CredentialMissingError(CollectorError):
    safe_error_code = "skipped_no_key"
    resulting_status = CollectorStatus.SKIPPED_NO_KEY

    def __init__(self, collector: str, credential_name: str) -> None:
        super().__init__(f"{collector} is missing the required credential {credential_name!r}.")


class CredentialInvalidError(CollectorError):
    safe_error_code = "invalid_credential"

    def __init__(self, collector: str) -> None:
        super().__init__(
            f"{collector}'s configured credential was rejected by the provider "
            "(invalid, expired, or missing entitlement)."
        )


class ProviderUnavailableError(CollectorError):
    safe_error_code = "provider_unavailable"

    def __init__(self, collector: str, detail: str) -> None:
        super().__init__(f"{collector}'s provider is unavailable: {detail}")


class ProviderSchemaError(CollectorError):
    """The provider responded, but its response did not match the shape this
    collector's parser expects (a versioned-parser / schema-drift failure)."""

    safe_error_code = "provider_schema_error"

    def __init__(self, collector: str, detail: str) -> None:
        super().__init__(f"{collector} could not parse the provider response: {detail}")


class CollectorTimeoutBudgetExceededError(CollectorError):
    safe_error_code = "collector_timeout"

    def __init__(self, collector: str) -> None:
        super().__init__(f"{collector} exceeded its collector time budget.")


class CollectorCancelledError(CollectorError):
    safe_error_code = "cancelled"

    def __init__(self, collector: str) -> None:
        super().__init__(f"{collector} was cancelled.")


def translate_gateway_error(collector: str, exc: GatewayError) -> CollectorError:
    """Map a lower-level gateway failure to the collector-facing taxonomy.

    BlockedDestinationError and DisallowedHostError should never happen for a
    correctly configured collector (they mean the collector declared a host it
    isn't allowed to call, or the safety boundary itself caught something) -
    they are treated as provider-unavailable rather than silently swallowed,
    so they still surface as a visible warning instead of crashing the job.
    """
    if isinstance(exc, ProviderTimeoutError):
        return CollectorTimeoutBudgetExceededError(collector)
    if isinstance(exc, ProviderRateLimitedError):
        return ProviderUnavailableError(collector, "rate-limited by the provider")
    if isinstance(exc, (MalformedResponseError, ResponseTooLargeError)):
        return ProviderSchemaError(collector, str(exc))
    if isinstance(exc, (BlockedDestinationError, DisallowedHostError)):
        return ProviderUnavailableError(collector, f"blocked by the outbound safety gateway: {exc}")
    return ProviderUnavailableError(collector, str(exc))
