"""Shared helpers for collector tests (not collected as tests itself)."""
from __future__ import annotations

import asyncio
import ipaddress
import time
from typing import Callable

import httpx

from app.collectors.base import CollectorContext
from app.collectors.job_findings import JobFindingsReader
from app.config import Settings
from app.models.enums import TargetType
from app.security.gateway import OutboundGateway
from app.security.network import StaticResolver, TargetDenyList
from app.security.targets import ClassifiedTarget
from app.services.cache import CacheAccess

TEST_SETTINGS = Settings(_env_file=None)


def make_gateway(handler: Callable[[httpx.Request], "asyncio.Future[httpx.Response]"], hosts_to_ips: dict[str, str]) -> OutboundGateway:
    resolver = StaticResolver(table={h: [ipaddress.ip_address(ip)] for h, ip in hosts_to_ips.items()})
    deny_list = TargetDenyList()
    deny_list.seed([ipaddress.ip_address("203.0.113.10")])  # arbitrary - not the point of these tests
    return OutboundGateway(
        transport=httpx.MockTransport(handler), resolver=resolver, settings=TEST_SETTINGS, deny_list=deny_list
    )


def make_context(session_factory, gateway: OutboundGateway, *, target_type: TargetType, target_normalized: str, collector: str, schema_version: str = "1", job_id: str = "job-1") -> CollectorContext:
    return CollectorContext(
        job_id=job_id,
        target=ClassifiedTarget(target_type=target_type, original_input=target_normalized, normalized=target_normalized),
        scope_note=None,
        gateway=gateway,
        cache=CacheAccess(session_factory=session_factory, collector=collector, schema_version=schema_version),
        job_findings=JobFindingsReader(session_factory=session_factory, job_id=job_id),
        cancellation=asyncio.Event(),
        job_deadline_monotonic=time.monotonic() + 300,
        collector_budget_seconds=90,
    )


def json_response(status: int, payload) -> httpx.Response:
    return httpx.Response(status, json=payload)
