"""Proves the process-wide socket block (pyproject.toml addopts = --disable-socket)
is actually wired up, not just configured and silently ignored. PRD 8.1 / 10.1:
no test may reach a real network, with no per-test exemptions."""
import socket

import pytest
from pytest_socket import SocketConnectBlockedError


def test_a_real_socket_connection_is_blocked() -> None:
    # Bare socket construction is allowed (asyncio's own Windows event-loop
    # plumbing needs that), but connecting anywhere outside the loopback
    # allow-list is not - see the addopts comment in pyproject.toml.
    with pytest.raises(SocketConnectBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))

    # A real asyncio-level connection is deliberately not exercised here:
    # ProactorEventLoop on Windows performs its connect through IOCP rather
    # than the plain socket.connect() call pytest-socket patches, so a test
    # asserting on that path is asserting on pytest-socket's Windows coverage,
    # not on any code this project owns. Every actual network call this
    # project makes goes through OutboundGateway's injected httpx transport,
    # which the gateway test suite covers directly and exhaustively.
