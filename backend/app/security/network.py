"""Destination-address policy: what an outbound request may never resolve to.

FR-03: resolved destination IPs in loopback, private, link-local, multicast, or
metadata ranges are blocked unless they belong to a fixed local test transport.
The assessed target and its resolved addresses are always denied as destinations
(handled separately by the deny-list, seeded per job — see gateway.py).
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Protocol

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# Cloud metadata endpoints are not covered by the standard private/link-local
# ranges on every platform, so they are listed explicitly.
_METADATA_ADDRESSES: frozenset[str] = frozenset(
    {
        "169.254.169.254",  # AWS / GCP / Azure IMDS
        "fd00:ec2::254",  # AWS IMDSv2 IPv6
    }
)


def is_forbidden_address(address: IPAddress) -> str | None:
    """Return a human-readable reason the address is forbidden, or None if it's allowed.

    Order matters: Python's ipaddress.is_private is a broad IANA special-purpose
    check that also covers loopback, link-local, and unspecified ranges, so the
    more specific checks run first to produce the most informative reason.
    """
    if str(address) in _METADATA_ADDRESSES:
        return "cloud metadata address"
    if address.is_unspecified:
        return "unspecified address"
    if address.is_loopback:
        return "loopback address"
    if address.is_link_local:
        return "link-local address"
    if address.is_multicast:
        return "multicast address"
    if address.is_private:
        return "private address"
    if address.is_reserved:
        return "reserved address"
    return None


class Resolver(Protocol):
    """Resolves a hostname to concrete IP addresses.

    Production implementations resolve provider hostnames via normal system DNS
    (this is not the assessed target, so ordinary resolution is fine) or, for the
    target itself, via the allowlisted DoH gateway (see gateway.py). Tests inject
    a fake resolver so no real socket is ever opened.
    """

    async def resolve(self, host: str) -> list[IPAddress]: ...


@dataclass
class StaticResolver:
    """A resolver with a fixed, injectable host -> addresses mapping. Test-only."""

    table: dict[str, list[IPAddress]] = field(default_factory=dict)

    async def resolve(self, host: str) -> list[IPAddress]:
        try:
            return self.table[host]
        except KeyError as exc:
            raise LookupError(f"No fake resolution configured for host {host!r}") from exc


class SystemResolver:
    """Resolves via the real system resolver. Used only in production, never in tests."""

    async def resolve(self, host: str) -> list[IPAddress]:
        import asyncio

        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, None)
        seen: dict[str, IPAddress] = {}
        for family, _, _, _, sockaddr in infos:
            ip_text = sockaddr[0]
            seen[ip_text] = ipaddress.ip_address(ip_text)
        return list(seen.values())


@dataclass
class TargetDenyList:
    """The per-job set of addresses that must never be contacted.

    FR-03: populated before any collector is claimed via a pre-job DoH resolution;
    addresses discovered later in the job are added immediately. No collector runs
    while this is unpopulated for the job.
    """

    _seeded: bool = False
    _addresses: set[str] = field(default_factory=set)

    @property
    def seeded(self) -> bool:
        return self._seeded

    def seed(self, addresses: list[IPAddress]) -> None:
        self._addresses.update(str(a) for a in addresses)
        self._seeded = True

    def add(self, addresses: list[IPAddress]) -> None:
        self._addresses.update(str(a) for a in addresses)

    def contains(self, address: IPAddress) -> bool:
        return str(address) in self._addresses
