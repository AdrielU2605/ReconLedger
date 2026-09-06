import pytest
from pydantic import ValidationError

from app.config import Settings


def test_default_bind_is_loopback() -> None:
    settings = Settings(_env_file=None)
    assert settings.bind_host == "127.0.0.1"


def test_non_loopback_bind_without_acknowledgement_is_refused() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, bind_host="0.0.0.0")


def test_non_loopback_bind_with_explicit_acknowledgement_is_allowed() -> None:
    settings = Settings(_env_file=None, bind_host="0.0.0.0", acknowledge_insecure_bind=True)
    assert settings.bind_host == "0.0.0.0"


def test_user_agent_names_app_version_and_repository() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_name in settings.user_agent
    assert settings.app_version in settings.user_agent
    assert settings.repository_url in settings.user_agent
