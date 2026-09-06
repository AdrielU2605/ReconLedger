"""Shared test fixtures.

The whole suite runs with --disable-socket (see pyproject.toml addopts), with no
per-test exemptions: every test that would otherwise touch the network must
inject a fake resolver and a fake httpx transport instead. If a test needs a
real connection, that is a bug in the test, not something to work around.
"""
from __future__ import annotations

import ipaddress

import pytest

from app.config import Settings
from app.security.network import StaticResolver, TargetDenyList


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


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
