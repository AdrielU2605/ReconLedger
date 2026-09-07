"""Shared test fixtures.

The whole suite runs with --disable-socket (see pyproject.toml addopts), with no
per-test exemptions: every test that would otherwise touch the network must
inject a fake resolver and a fake httpx transport instead. If a test needs a
real connection, that is a bug in the test, not something to work around.
"""
from __future__ import annotations

import ipaddress
from pathlib import Path

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig

from app.config import Settings
from app.db.session import create_engine, enable_wal_mode, make_session_factory
from app.security.network import StaticResolver, TargetDenyList

BACKEND_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    """A throwaway SQLite database, migrated to head via the real Alembic
    migrations (not Base.metadata.create_all()) - this is also how the FTS5
    virtual table and its sync triggers actually get exercised by the suite."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    config = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    alembic_command.upgrade(config, "head")
    return url


@pytest.fixture
async def session_factory(db_url: str):
    engine = create_engine(db_url)
    async with enable_wal_mode(engine):
        pass
    factory = make_session_factory(engine)
    yield factory
    await engine.dispose()


DENY_LISTED_ADDRESS = "93.184.216.34"
"""A globally-routable address used only as a fake deny-listed value in tests.

It is deliberately NOT a private/reserved/documentation address, so that
tests exercising the deny-list branch of ValidatingTransport aren't
short-circuited by the earlier forbidden-range check. Nothing in the test
suite ever opens a real socket to it (--disable-socket is enforced globally).
"""

ALLOWED_ADDRESS = "8.8.8.8"
"""A globally-routable address used as the "this request is fine" fixture value."""


@pytest.fixture
def seeded_deny_list() -> TargetDenyList:
    deny_list = TargetDenyList()
    deny_list.seed([ipaddress.ip_address(DENY_LISTED_ADDRESS)])
    return deny_list


@pytest.fixture
def public_resolver() -> StaticResolver:
    """A resolver that only knows about well-behaved public provider addresses."""
    return StaticResolver(
        table={
            "provider.example": [ipaddress.ip_address(ALLOWED_ADDRESS)],
        }
    )
