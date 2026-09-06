"""Application configuration.

Loaded from environment variables or a developer-local .env file (never committed;
see .env.example). PRD 8.3: bind to loopback by default, and require an explicit
acknowledgement to bind anywhere else.
"""
from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RECONLEDGER_", extra="ignore")

    bind_host: str = "127.0.0.1"
    bind_port: int = 8000
    acknowledge_insecure_bind: bool = False

    log_level: str = "INFO"

    # FR-03 / FR-04 defaults (documented per-provider overrides live on each collector).
    connect_timeout_seconds: float = 10.0
    default_request_timeout_seconds: float = 30.0
    collector_budget_seconds: float = 90.0
    job_budget_seconds: float = 300.0

    retry_max_attempts: int = 3
    retry_base_delay_seconds: float = 0.5
    retry_cap_delay_seconds: float = 8.0

    app_name: str = "ReconLedger"
    app_version: str = "0.1.0"
    repository_url: str = "https://github.com/AdrielU2605/ReconLedger"

    @model_validator(mode="after")
    def _validate_bind(self) -> "Settings":
        loopback_hosts = {"127.0.0.1", "::1", "localhost"}
        if self.bind_host not in loopback_hosts and not self.acknowledge_insecure_bind:
            raise ValueError(
                "Binding to a non-loopback host requires "
                "RECONLEDGER_ACKNOWLEDGE_INSECURE_BIND=true to be set explicitly. "
                f"Refusing to bind to {self.bind_host!r}."
            )
        return self

    @property
    def user_agent(self) -> str:
        return f"{self.app_name}/{self.app_version} (+{self.repository_url})"


def get_settings() -> Settings:
    return Settings()
