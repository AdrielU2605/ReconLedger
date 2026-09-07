"""Seeds a job's target deny-list from its already-validated, classified
target (FR-03). No collector is dispatched until this completes.
"""
from __future__ import annotations

import ipaddress

from app.models.enums import TargetType
from app.security.doh_resolve import resolve_addresses_via_google_doh
from app.security.gateway import OutboundGateway
from app.security.targets import ClassifiedTarget


async def seed_deny_list_for_target(gateway: OutboundGateway, target: ClassifiedTarget) -> None:
    if target.target_type is TargetType.IP:
        gateway.deny_list.seed([ipaddress.ip_address(target.normalized)])
    elif target.target_type is TargetType.CIDR:
        gateway.deny_list.seed_networks([ipaddress.ip_network(target.normalized)])
    elif target.target_type is TargetType.DOMAIN:
        await gateway.seed_deny_list(target.normalized, resolve_addresses_via_google_doh)
    else:
        # Organization targets are rejected at job creation (not assessable in
        # the MVP) and should never reach dispatch.
        raise AssertionError(f"Cannot seed a deny-list for target type {target.target_type!r}.")
