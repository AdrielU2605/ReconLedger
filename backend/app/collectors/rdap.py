"""RDAP collector (PRD FR-08 provider matrix row / FR-02 contract, 8.1).

Registration data access is federated: the IANA bootstrap registries map a
TLD (or an IP block) to the registry's own RDAP base URL, which is not known
until that bootstrap file is fetched. provider_hosts therefore only lists the
bootstrap host itself; the registry host contacted for any given target is
validated against the same bootstrap file's own entries before the request
is made and again if a redirect is followed (PRD 8.1: "RDAP redirects/
bootstrap results are accepted only when the destination is HTTPS, matches
an approved registry service entry, and resolves outside prohibited address
ranges").

Re-checked against ICANN's RDAP documentation and the live IANA bootstrap
files (data.iana.org/rdap/dns.json, ipv4.json, ipv6.json) on 2026-09-06.
"""
from __future__ import annotations

import ipaddress
from datetime import datetime, timezone
from typing import Any

import httpx

from app.collectors.base import CachePolicy, CollectedFinding, CollectorContext, CollectorMetadata, RatePolicy
from app.collectors.caching import get_cached_findings, store_findings_in_cache
from app.collectors.errors import ProviderSchemaError, ProviderUnavailableError
from app.models.enums import Category, TargetType
from app.security.gateway import parse_json_safely
from app.services.cache import CACHE_STATUS_EMPTY, CACHE_STATUS_SUCCESS, compute_cache_key
from app.services.fingerprint import compute_fingerprint

BOOTSTRAP_HOST = "data.iana.org"
DNS_BOOTSTRAP_URL = f"https://{BOOTSTRAP_HOST}/rdap/dns.json"
IPV4_BOOTSTRAP_URL = f"https://{BOOTSTRAP_HOST}/rdap/ipv4.json"
IPV6_BOOTSTRAP_URL = f"https://{BOOTSTRAP_HOST}/rdap/ipv6.json"

SCHEMA_VERSION = "1"
POSITIVE_TTL_SECONDS = 86400  # PRD FR-05: RDAP/RIPEstat/CT 24 hours
NEGATIVE_TTL_SECONDS = 3600

metadata = CollectorMetadata(
    name="rdap",
    display_name="RDAP",
    supported_targets=frozenset({TargetType.DOMAIN, TargetType.IP}),
    categories=frozenset({Category.NETWORK_FOOTPRINT}),
    required_credentials=(),
    provider_hosts=frozenset({BOOTSTRAP_HOST}),
    key_help_url="https://www.icann.org/en/contracted-parties/registry-operators/resources/registration-data-access-protocol",
    rate_policy=RatePolicy(requests_per_period=5, period_seconds=1, burst=5, concurrency=2),
    cache_policy=CachePolicy(
        positive_ttl_seconds=POSITIVE_TTL_SECONDS, negative_ttl_seconds=NEGATIVE_TTL_SECONDS, schema_version=SCHEMA_VERSION
    ),
)


def _parse_bootstrap_services(data: Any) -> list[tuple[list[str], list[str]]]:
    services = data.get("services") if isinstance(data, dict) else None
    if not isinstance(services, list):
        raise ProviderSchemaError("rdap", "bootstrap file missing a 'services' array")
    parsed: list[tuple[list[str], list[str]]] = []
    for entry in services:
        if isinstance(entry, list) and len(entry) >= 2 and isinstance(entry[0], list) and isinstance(entry[1], list):
            parsed.append((entry[0], entry[1]))
    return parsed


def _find_dns_base_urls(services: list[tuple[list[str], list[str]]], tld: str) -> list[str]:
    for tlds, urls in services:
        if tld in tlds:
            return urls
    return []


def _find_ip_base_urls(services: list[tuple[list[str], list[str]]], address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> list[str]:
    for cidrs, urls in services:
        for cidr in cidrs:
            try:
                network = ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                continue
            if network.version == address.version and address in network:
                return urls
    return []


def _all_bootstrap_hosts(services: list[tuple[list[str], list[str]]]) -> frozenset[str]:
    hosts = set()
    for _keys, urls in services:
        for url in urls:
            host = httpx.URL(url).host
            if host:
                hosts.add(host)
    return frozenset(hosts)


def _extract_vcard_fn(vcard_array: Any) -> str | None:
    if not isinstance(vcard_array, list) or len(vcard_array) < 2 or not isinstance(vcard_array[1], list):
        return None
    for prop in vcard_array[1]:
        if isinstance(prop, list) and len(prop) >= 4 and prop[0] == "fn":
            value = prop[3]
            return value if isinstance(value, str) else None
    return None


_REDACTION_MARKERS = ("redacted", "not disclosed", "withheld")


def _entity_display_name(entity: dict[str, Any]) -> str:
    name = _extract_vcard_fn(entity.get("vcardArray"))
    if not name or any(marker in name.lower() for marker in _REDACTION_MARKERS):
        return "not disclosed by registrar"
    return name


def _normalize_rdap_record(record: dict[str, Any], target: str) -> dict[str, Any]:
    events = {}
    for event in record.get("events") or []:
        action = event.get("eventAction")
        if action:
            events[action] = event.get("eventDate")

    entities = []
    for entity in record.get("entities") or []:
        entities.append({"roles": entity.get("roles") or [], "name": _entity_display_name(entity)})

    registrar = next((e["name"] for e in entities if "registrar" in e["roles"]), "not disclosed by registrar")

    return {
        "target": target,
        "handle": record.get("handle"),
        "ldh_name": record.get("ldhName"),
        "status": record.get("status") or [],
        "nameservers": [ns.get("ldhName") for ns in (record.get("nameservers") or []) if ns.get("ldhName")],
        "events": events,
        "entities": entities,
        "registrar": registrar,
    }


def _build_finding(normalized: dict[str, Any], raw: dict[str, Any], source_url: str, target: str) -> CollectedFinding:
    now = datetime.now(timezone.utc)
    summary_parts = [f"Registrar: {normalized['registrar']}"]
    if normalized["status"]:
        summary_parts.append(f"Status: {', '.join(normalized['status'])}")
    if normalized["events"].get("registration"):
        summary_parts.append(f"Registered: {normalized['events']['registration']}")
    return CollectedFinding(
        category=Category.NETWORK_FOOTPRINT,
        kind="rdap.registration",
        title=f"RDAP record for {target}",
        summary="; ".join(summary_parts),
        normalized_value=normalized,
        raw_evidence=raw,
        source_url=source_url,
        retrieved_at=now,
        fingerprint=compute_fingerprint("rdap", "rdap.registration", {"target": target}),
    )


async def _fetch_bootstrap(context: CollectorContext, url: str) -> list[tuple[list[str], list[str]]]:
    cache_key = compute_cache_key(collector="rdap", schema_version=SCHEMA_VERSION, target_normalized=url, variant="bootstrap")
    cached = await context.cache.get(cache_key)
    if cached is not None:
        return _parse_bootstrap_services(cached.response_json)

    response = await context.gateway.get(url=url, allowed_hosts=frozenset({BOOTSTRAP_HOST}))
    data = parse_json_safely(response, host=BOOTSTRAP_HOST)
    services = _parse_bootstrap_services(data)
    await context.cache.set(
        cache_key,
        status=CACHE_STATUS_SUCCESS,
        response_json=data,
        normalized_findings_json={},
        ttl_seconds=POSITIVE_TTL_SECONDS,
    )
    return services


async def run(context: CollectorContext) -> list[CollectedFinding]:
    target = context.target
    cache_key = compute_cache_key(collector="rdap", schema_version=SCHEMA_VERSION, target_normalized=target.normalized)
    cached_findings = await get_cached_findings(context, cache_key)
    if cached_findings is not None:
        return cached_findings

    if target.target_type is TargetType.DOMAIN:
        services = await _fetch_bootstrap(context, DNS_BOOTSTRAP_URL)
        labels = target.normalized.split(".")
        tld = labels[-1]
        base_urls = _find_dns_base_urls(services, tld)
        query_path = f"domain/{target.normalized}"
    else:
        address = ipaddress.ip_address(target.normalized)
        bootstrap_url = IPV4_BOOTSTRAP_URL if address.version == 4 else IPV6_BOOTSTRAP_URL
        services = await _fetch_bootstrap(context, bootstrap_url)
        base_urls = _find_ip_base_urls(services, address)
        query_path = f"ip/{target.normalized}"

    if not base_urls:
        raise ProviderUnavailableError("rdap", f"no RDAP service is registered for {target.normalized!r}")

    approved_hosts = _all_bootstrap_hosts(services) | {BOOTSTRAP_HOST}
    base_url = base_urls[0] if base_urls[0].endswith("/") else base_urls[0] + "/"
    query_url = base_url + query_path
    registry_host = httpx.URL(base_url).host

    response = await context.gateway.get(
        url=query_url,
        allowed_hosts=frozenset({BOOTSTRAP_HOST, registry_host}),
        allow_redirect_to=lambda host: host in approved_hosts,
    )

    if response.status_code == 404:
        await store_findings_in_cache(
            context.cache, cache_key, [], status=CACHE_STATUS_EMPTY, response_json={"status": 404}, ttl_seconds=NEGATIVE_TTL_SECONDS
        )
        return []

    if response.status_code != 200:
        raise ProviderUnavailableError("rdap", f"unexpected status {response.status_code} from {registry_host}")

    data = parse_json_safely(response, host=registry_host)
    if not isinstance(data, dict):
        raise ProviderSchemaError("rdap", "response was not a JSON object")

    normalized = _normalize_rdap_record(data, target.normalized)
    finding = _build_finding(normalized, data, query_url, target.normalized)

    await store_findings_in_cache(
        context.cache, cache_key, [finding], status=CACHE_STATUS_SUCCESS, response_json=data, ttl_seconds=POSITIVE_TTL_SECONDS
    )
    return [finding]
