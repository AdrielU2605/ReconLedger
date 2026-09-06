"""Secret-safe logging support (PRD 8.3, 9 Observability).

Redacts configured secret values and sensitive headers from anything that reaches
a structured log record. Evidence-level redaction (stripping secrets from raw
provider payloads before persistence, FR-06) is built in CP3 alongside the first
real collectors, once there is real provider evidence to redact.
"""
from __future__ import annotations

_SENSITIVE_HEADER_NAMES: frozenset[str] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
        "proxy-authorization",
    }
)

_REDACTED = "[redacted]"


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of headers with sensitive header values replaced."""
    return {
        key: (_REDACTED if key.lower() in _SENSITIVE_HEADER_NAMES else value)
        for key, value in headers.items()
    }


def redact_secrets(text: str, secrets: list[str]) -> str:
    """Replace every occurrence of every non-empty configured secret value in `text`."""
    result = text
    for secret in secrets:
        if secret:
            result = result.replace(secret, _REDACTED)
    return result


class SecretRegistry:
    """Tracks configured secret values for this process so log records can redact them.

    Collectors register their credential values here (never the credential names,
    which are safe to log) as soon as they are loaded from the environment.
    """

    def __init__(self) -> None:
        self._secrets: set[str] = set()

    def register(self, value: str | None) -> None:
        if value:
            self._secrets.add(value)

    def redact(self, text: str) -> str:
        return redact_secrets(text, list(self._secrets))


secret_registry = SecretRegistry()
