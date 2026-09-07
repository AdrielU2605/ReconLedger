"""Minimal DoH address resolution used only to seed the per-job target
deny-list (FR-03) before any collector is dispatched.

This is deliberately narrow - A/AAAA lookup only, no record-type richness.
The full DNS-and-mail-posture collector (FR-07: SPF/DMARC/DKIM, primary +
secondary resolver, resolver-disagreement-as-evidence) is a separate,
richer collector built in CP3. Both ultimately call the same allowlisted
provider through the same gateway.
"""
from __future__ import annotations

import ipaddress

import httpx

from app.security.gateway import OutboundGateway, parse_json_safely
from app.security.network import IPAddress

GOOGLE_DOH_HOST = "dns.google"
GOOGLE_DOH_ALLOWED_HOSTS: frozenset[str] = frozenset({GOOGLE_DOH_HOST})


async def resolve_addresses_via_google_doh(gateway: OutboundGateway, hostname: str) -> list[IPAddress]:
    addresses: list[IPAddress] = []
    for record_type in ("A", "AAAA"):
        url = httpx.URL(f"https://{GOOGLE_DOH_HOST}/resolve").copy_with(
            params={"name": hostname, "type": record_type}
        )
        response = await gateway.get(url=str(url), allowed_hosts=GOOGLE_DOH_ALLOWED_HOSTS)
        data = parse_json_safely(response, host=GOOGLE_DOH_HOST)
        for answer in data.get("Answer") or []:
            try:
                addresses.append(ipaddress.ip_address(answer["data"]))
            except (ValueError, KeyError):
                continue  # e.g. a CNAME chain entry, not an address record
    return addresses
