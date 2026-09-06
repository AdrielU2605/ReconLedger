import logging

from app.logging_config import CorrelationJsonFormatter, bind_correlation
from app.security.redaction import SecretRegistry, redact_headers, redact_secrets


def test_redact_headers_hides_sensitive_values_only() -> None:
    headers = {
        "Authorization": "Bearer super-secret-token",
        "Cookie": "session=abc123",
        "Content-Type": "application/json",
    }
    redacted = redact_headers(headers)
    assert redacted["Authorization"] == "[redacted]"
    assert redacted["Cookie"] == "[redacted]"
    assert redacted["Content-Type"] == "application/json"


def test_redact_secrets_replaces_every_occurrence() -> None:
    text = "key=sk-abc123 and again sk-abc123 in the same message"
    assert redact_secrets(text, ["sk-abc123"]) == "key=[redacted] and again [redacted] in the same message"


def test_redact_secrets_ignores_empty_values() -> None:
    assert redact_secrets("nothing to hide", ["", None]) == "nothing to hide"  # type: ignore[list-item]


def test_secret_registry_redacts_registered_values() -> None:
    registry = SecretRegistry()
    registry.register("sk-abc123")
    registry.register(None)
    assert registry.redact("token is sk-abc123 here") == "token is [redacted] here"


def test_log_formatter_never_emits_a_registered_secret(caplog) -> None:
    from app.security.redaction import secret_registry

    secret_registry.register("sk-super-secret")
    bind_correlation(job_id="job-1", collector="rdap")

    record = logging.LogRecord(
        name="reconledger.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="provider call used key sk-super-secret",
        args=(),
        exc_info=None,
    )
    formatted = CorrelationJsonFormatter().format(record)

    assert "sk-super-secret" not in formatted
    assert "[redacted]" in formatted
    assert '"job_id": "job-1"' in formatted
    assert '"collector": "rdap"' in formatted
