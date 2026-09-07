"""DNS-over-HTTPS collector (PRD FR-07).

Queries A, AAAA, CNAME, MX, NS, SOA, TXT, and _dmarc TXT separately - never
ANY. A and AAAA are queried against both the primary (Google) and secondary
(Cloudflare) allowlisted resolvers so resolver agreement/disagreement is
itself recorded as evidence; other record types query the primary only,
falling back to the secondary if the primary resolver itself fails (a
provider outage must not fail the collector). DKIM is parsed only from
already-collected passive evidence (archived headers, etc.) - no such
evidence source exists yet as of CP3, so no dns.dkim finding is produced
here; its absence is "Unknown", not "missing".

Re-checked against Google's and Cloudflare's current DoH JSON API docs on
2026-09-06.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.collectors.base import CachePolicy, CollectedFinding, CollectorContext, CollectorMetadata, RatePolicy
from app.collectors.caching import get_cached_findings, store_findings_in_cache
from app.collectors.errors import ProviderUnavailableError
from app.models.enums import Category, TargetType
from app.security.errors import GatewayError
from app.security.gateway import parse_json_safely
from app.services.cache import CACHE_STATUS_EMPTY, CACHE_STATUS_SUCCESS, compute_cache_key
from app.services.fingerprint import compute_fingerprint

PRIMARY_HOST = "dns.google"
SECONDARY_HOST = "cloudflare-dns.com"
ALLOWED_HOSTS = frozenset({PRIMARY_HOST, SECONDARY_HOST})

SCHEMA_VERSION = "1"
POSITIVE_TTL_SECONDS = 1800  # bounded by observed record TTL; this is the collector's own cap
NEGATIVE_TTL_SECONDS = 600

_RECORD_TYPES = ("A", "AAAA", "CNAME", "MX", "NS", "SOA", "TXT")

metadata = CollectorMetadata(
    name="dns_doh",
    display_name="DNS (DNS-over-HTTPS)",
    supported_targets=frozenset({TargetType.DOMAIN}),
    categories=frozenset({Category.NETWORK_FOOTPRINT}),
    required_credentials=(),
    provider_hosts=ALLOWED_HOSTS,
    key_help_url="https://developers.google.com/speed/public-dns/docs/doh/json",
    rate_policy=RatePolicy(requests_per_period=20, period_seconds=1, burst=20, concurrency=4),
    cache_policy=CachePolicy(
        positive_ttl_seconds=POSITIVE_TTL_SECONDS, negative_ttl_seconds=NEGATIVE_TTL_SECONDS, schema_version=SCHEMA_VERSION
    ),
)


async def _query(context: CollectorContext, host: str, name: str, record_type: str) -> dict[str, Any]:
    if host == PRIMARY_HOST:
        url = httpx.URL(f"https://{host}/resolve").copy_with(params={"name": name, "type": record_type})
        headers = None
    else:
        url = httpx.URL(f"https://{host}/dns-query").copy_with(params={"name": name, "type": record_type})
        headers = {"Accept": "application/dns-json"}
    response = await context.gateway.get(url=str(url), allowed_hosts=ALLOWED_HOSTS, headers=headers)
    result: dict[str, Any] = parse_json_safely(response, host=host)
    return result


async def _query_with_fallback(context: CollectorContext, name: str, record_type: str) -> tuple[dict[str, Any], str]:
    try:
        return await _query(context, PRIMARY_HOST, name, record_type), PRIMARY_HOST
    except GatewayError:
        return await _query(context, SECONDARY_HOST, name, record_type), SECONDARY_HOST


def _addresses_from_answer(data: dict[str, Any]) -> list[str]:
    return sorted({a["data"] for a in (data.get("Answer") or []) if "data" in a})


def _parse_txt_datum(raw: str) -> str:
    if raw.startswith('"'):
        return "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', raw)).replace('\\"', '"')
    return raw


def _txt_values(data: dict[str, Any]) -> list[str]:
    return [_parse_txt_datum(a["data"]) for a in (data.get("Answer") or []) if "data" in a]


def _finding(kind: str, title: str, summary: str, normalized: dict[str, Any], raw: dict[str, Any], target: str, source_host: str, identity: dict[str, Any] | None = None) -> CollectedFinding:
    return CollectedFinding(
        category=Category.NETWORK_FOOTPRINT,
        kind=kind,
        title=title,
        summary=summary,
        normalized_value=normalized,
        raw_evidence=raw,
        source_url=f"https://{source_host}/",
        retrieved_at=datetime.now(timezone.utc),
        fingerprint=compute_fingerprint("dns_doh", kind, identity if identity is not None else {"target": target}),
    )


async def run(context: CollectorContext) -> list[CollectedFinding]:
    target = context.target
    cache_key = compute_cache_key(collector="dns_doh", schema_version=SCHEMA_VERSION, target_normalized=target.normalized)
    cached = await get_cached_findings(context, cache_key)
    if cached is not None:
        return cached

    findings: list[CollectedFinding] = []
    domain = target.normalized

    # A / AAAA queried against both resolvers - agreement/disagreement is evidence.
    for record_type, kind in (("A", "dns.a"), ("AAAA", "dns.aaaa")):
        try:
            primary_data = await _query(context, PRIMARY_HOST, domain, record_type)
        except GatewayError:
            primary_data = None
        try:
            secondary_data = await _query(context, SECONDARY_HOST, domain, record_type)
        except GatewayError:
            secondary_data = None

        primary_addrs = _addresses_from_answer(primary_data) if primary_data else []
        secondary_addrs = _addresses_from_answer(secondary_data) if secondary_data else []

        if not primary_data and not secondary_data:
            raise ProviderUnavailableError("dns_doh", f"both DoH resolvers failed for {record_type} {domain}")

        chosen_addrs = primary_addrs or secondary_addrs
        if chosen_addrs:
            chosen_raw = primary_data if primary_addrs else secondary_data
            assert chosen_raw is not None
            findings.append(
                _finding(
                    kind, f"{record_type} records for {domain}", f"{len(chosen_addrs)} {record_type} record(s) observed",
                    {"addresses": chosen_addrs}, chosen_raw, domain, PRIMARY_HOST if primary_addrs else SECONDARY_HOST,
                )
            )

        if primary_data and secondary_data and primary_addrs != secondary_addrs:
            findings.append(
                _finding(
                    "dns.resolver_disagreement",
                    f"Resolvers disagree on {record_type} for {domain}",
                    f"Primary observed {primary_addrs or 'none'}; secondary observed {secondary_addrs or 'none'}",
                    {"record_type": record_type, "primary": primary_addrs, "secondary": secondary_addrs},
                    {"primary": primary_data, "secondary": secondary_data},
                    domain,
                    PRIMARY_HOST,
                    identity={"target": domain, "record_type": record_type},
                )
            )

    # CNAME / MX / NS / SOA / TXT: primary with secondary fallback only.
    cname_data, cname_host = await _query_with_fallback(context, domain, "CNAME")
    cname_values = [a["data"].rstrip(".") for a in (cname_data.get("Answer") or []) if "data" in a]
    if cname_values:
        findings.append(_finding("dns.cname", f"CNAME for {domain}", f"Aliased to {cname_values[0]}", {"target": cname_values[0]}, cname_data, domain, cname_host))

    mx_data, mx_host = await _query_with_fallback(context, domain, "MX")
    mx_records = []
    for answer in mx_data.get("Answer") or []:
        parts = str(answer.get("data", "")).split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            mx_records.append({"preference": int(parts[0]), "exchange": parts[1].rstrip(".")})
    if mx_records:
        findings.append(_finding("dns.mx", f"MX records for {domain}", f"{len(mx_records)} mail exchanger(s) observed", {"records": mx_records}, mx_data, domain, mx_host))

    ns_data, ns_host = await _query_with_fallback(context, domain, "NS")
    nameservers = sorted({a["data"].rstrip(".") for a in (ns_data.get("Answer") or []) if "data" in a})
    if nameservers:
        findings.append(_finding("dns.ns", f"Nameservers for {domain}", f"{len(nameservers)} nameserver(s) observed", {"nameservers": nameservers}, ns_data, domain, ns_host))

    soa_data, soa_host = await _query_with_fallback(context, domain, "SOA")
    soa_answer = next(iter(soa_data.get("Answer") or []), None)
    if soa_answer and "data" in soa_answer:
        fields = str(soa_answer["data"]).split()
        if len(fields) == 7:
            soa = {
                "mname": fields[0].rstrip("."), "rname": fields[1].rstrip("."), "serial": fields[2],
                "refresh": fields[3], "retry": fields[4], "expire": fields[5], "minimum": fields[6],
            }
            findings.append(_finding("dns.soa", f"SOA record for {domain}", f"Primary nameserver {soa['mname']}", soa, soa_data, domain, soa_host))

    txt_data, txt_host = await _query_with_fallback(context, domain, "TXT")
    txt_values = _txt_values(txt_data)
    if txt_values:
        findings.append(_finding("dns.txt", f"TXT records for {domain}", f"{len(txt_values)} TXT record(s) observed", {"records": txt_values}, txt_data, domain, txt_host))

    spf_records = [v for v in txt_values if v.lower().startswith("v=spf1")]
    if spf_records:
        spf_normalized: dict[str, Any] = {"record": spf_records[0], "mechanisms": spf_records[0].split()}
        if len(spf_records) > 1:
            spf_normalized["warning"] = "multiple SPF TXT records observed; only the first is used here"
            spf_normalized["all_records"] = spf_records
        findings.append(_finding("dns.spf", f"SPF policy for {domain}", "SPF record observed", spf_normalized, txt_data, domain, txt_host))

    dmarc_name = f"_dmarc.{domain}"
    dmarc_data, dmarc_host = await _query_with_fallback(context, dmarc_name, "TXT")
    dmarc_values = [v for v in _txt_values(dmarc_data) if v.lower().startswith("v=dmarc1")]
    if dmarc_values:
        tags = dict(
            (part.split("=", 1)[0].strip(), part.split("=", 1)[1].strip())
            for part in dmarc_values[0].split(";")
            if "=" in part
        )
        dmarc_normalized: dict[str, Any] = {"record": dmarc_values[0], "tags": tags}
        if len(dmarc_values) > 1:
            dmarc_normalized["warning"] = "multiple DMARC TXT records observed; only the first is used here"
            dmarc_normalized["all_records"] = dmarc_values
        findings.append(_finding("dns.dmarc", f"DMARC policy for {domain}", "DMARC record observed - policy not independently verified beyond this resolver", dmarc_normalized, dmarc_data, domain, dmarc_host, identity={"target": domain, "kind": "dmarc"}))

    status = CACHE_STATUS_SUCCESS if findings else CACHE_STATUS_EMPTY
    ttl = POSITIVE_TTL_SECONDS if findings else NEGATIVE_TTL_SECONDS
    await store_findings_in_cache(context.cache, cache_key, findings, status=status, response_json={"finding_count": len(findings)}, ttl_seconds=ttl)
    return findings
