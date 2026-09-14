"""Technology inference (PRD FR-10): evidence-backed rules over already
collected passive evidence only. Makes no network call of its own and is
always dispatched after every other selected collector for the job has
finished (see app.jobs.runner.DEFERRED_UNTIL_LAST_COLLECTORS), since its
input is those collectors' own persisted findings.

Signal sources, each optional and independent - a missing source (e.g. the
domain wasn't selected for wayback/commoncrawl, or crt.sh timed out)
simply means fewer rules fire, never an error:
- dns.ns (nameserver hosting/CDN patterns)
- dns.mx (mail provider patterns)
- wayback.sample / commoncrawl.sample (archived response headers and a
  bounded HTML snippet - server/x-powered-by headers, generator meta tags,
  well-known asset-path fingerprints)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.collectors.base import CachePolicy, CollectedFinding, CollectorContext, CollectorMetadata, RatePolicy
from app.models.db import Finding
from app.models.enums import Category, Confidence, TargetType
from app.services.fingerprint import compute_fingerprint

SCHEMA_VERSION = "1"

metadata = CollectorMetadata(
    name="technology",
    display_name="Technology inference",
    supported_targets=frozenset({TargetType.DOMAIN}),
    categories=frozenset({Category.TECHNOLOGY_STACK}),
    required_credentials=(),
    provider_hosts=frozenset(),  # makes no network call at all
    key_help_url=None,
    rate_policy=RatePolicy(requests_per_period=1, period_seconds=1, burst=1, concurrency=1),
    cache_policy=CachePolicy(positive_ttl_seconds=0, negative_ttl_seconds=0, schema_version=SCHEMA_VERSION),
)

_INPUT_KINDS = {"dns.ns", "dns.mx", "wayback.sample", "commoncrawl.sample"}


@dataclass
class _Detection:
    rule_id: str
    technology: str
    confidence: Confidence
    explanation: str
    supporting_ids: set[str] = field(default_factory=set)
    source_url: str = ""


def _merge(detections: dict[tuple[str, str], _Detection], detection: _Detection, source: Finding) -> None:
    key = (detection.rule_id, detection.technology)
    existing = detections.get(key)
    if existing is None:
        detection.supporting_ids.add(source.id)
        detection.source_url = source.source_url
        detections[key] = detection
    else:
        existing.supporting_ids.add(source.id)


def _rules_from_nameservers(finding: Finding, detections: dict[tuple[str, str], _Detection]) -> None:
    nameservers = [str(ns).lower() for ns in (finding.normalized_value_json.get("nameservers") or [])]
    patterns = (
        ("ns.cloudflare_dns", "cloudflare.com", "Cloudflare (DNS/CDN)"),
        ("ns.route53", "awsdns", "Amazon Route 53"),
        ("ns.godaddy_dns", "domaincontrol.com", "GoDaddy DNS"),
        ("ns.azure_dns", "azure-dns", "Azure DNS"),
    )
    for rule_id, needle, technology in patterns:
        if any(needle in ns for ns in nameservers):
            _merge(
                detections,
                _Detection(rule_id, technology, Confidence.MEDIUM, f"A nameserver contained {needle!r}."),
                finding,
            )


def _rules_from_mx(finding: Finding, detections: dict[tuple[str, str], _Detection]) -> None:
    exchanges = [str(r.get("exchange", "")).lower() for r in (finding.normalized_value_json.get("records") or [])]
    patterns = (
        ("mx.google_workspace", ("google.com", "googlemail.com"), "Google Workspace (Gmail)"),
        ("mx.microsoft_365", ("outlook.com", "protection.outlook.com"), "Microsoft 365"),
    )
    for rule_id, needles, technology in patterns:
        if any(needle in exchange for exchange in exchanges for needle in needles):
            _merge(
                detections,
                _Detection(rule_id, technology, Confidence.MEDIUM, "A mail exchanger record matched a known provider."),
                finding,
            )


_GENERATOR_META_RE = re.compile(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)', re.IGNORECASE)

_HEADER_RULES = (
    ("header.server_cloudflare", "server", "cloudflare", "Cloudflare", Confidence.MEDIUM),
    ("header.server_nginx", "server", "nginx", "nginx", Confidence.LOW),
    ("header.server_apache", "server", "apache", "Apache HTTP Server", Confidence.LOW),
    ("header.server_gws", "server", "gws", "Google Web Server", Confidence.LOW),
    ("header.powered_by_php", "x-powered-by", "php", "PHP", Confidence.MEDIUM),
    ("header.powered_by_express", "x-powered-by", "express", "Express (Node.js)", Confidence.MEDIUM),
    ("header.powered_by_aspnet", "x-powered-by", "asp.net", "ASP.NET", Confidence.MEDIUM),
)

_BODY_SUBSTRING_RULES = (
    ("body.wordpress_paths", ("wp-content/", "wp-includes/"), "WordPress", Confidence.HIGH),
    ("body.shopify", ("cdn.shopify.com", ".myshopify.com"), "Shopify", Confidence.HIGH),
    ("body.wix", ("static.wixstatic.com",), "Wix", Confidence.HIGH),
)


def _rules_from_archived_sample(finding: Finding, detections: dict[tuple[str, str], _Detection]) -> None:
    headers = {str(k).lower(): str(v).lower() for k, v in (finding.normalized_value_json.get("headers") or {}).items()}
    for rule_id, header_name, needle, technology, confidence in _HEADER_RULES:
        value = headers.get(header_name)
        if value and needle in value:
            _merge(
                detections,
                _Detection(rule_id, technology, confidence, f"The {header_name!r} response header contained {needle!r}."),
                finding,
            )

    body = str((finding.raw_evidence_json or {}).get("body_snippet") or "")
    body_lower = body.lower()
    for rule_id, needles, technology, confidence in _BODY_SUBSTRING_RULES:
        if any(needle in body_lower for needle in needles):
            _merge(
                detections,
                _Detection(rule_id, technology, confidence, f"Archived HTML referenced {needles[0]!r}."),
                finding,
            )

    generator_match = _GENERATOR_META_RE.search(body)
    if generator_match:
        generator = generator_match.group(1).strip()
        if "wordpress" in generator.lower():
            _merge(
                detections,
                _Detection("body.generator_wordpress", "WordPress", Confidence.HIGH, f"<meta name=generator> declared {generator!r}."),
                finding,
            )


async def run(context: CollectorContext) -> list[CollectedFinding]:
    findings = await context.job_findings.get(kinds=_INPUT_KINDS)
    detections: dict[tuple[str, str], _Detection] = {}

    for finding in findings:
        if finding.kind == "dns.ns":
            _rules_from_nameservers(finding, detections)
        elif finding.kind == "dns.mx":
            _rules_from_mx(finding, detections)
        elif finding.kind in ("wayback.sample", "commoncrawl.sample"):
            _rules_from_archived_sample(finding, detections)

    now = datetime.now(timezone.utc)
    target = context.target.normalized
    results: list[CollectedFinding] = []
    for (rule_id, technology), detection in sorted(detections.items()):
        results.append(
            CollectedFinding(
                category=Category.TECHNOLOGY_STACK,
                kind="tech.inference",
                title=technology,
                summary=detection.explanation,
                # supporting_finding_ids deliberately lives only in raw_evidence, not
                # normalized_value: those IDs are this run's own Finding row UUIDs, always
                # different from run to run even when the inference itself is identical,
                # and the diff engine (app/services/diff.py) compares normalized_value for
                # equality - including them there would make every technology finding show
                # as "changed" on every rerun, never "unchanged".
                normalized_value={
                    "rule_id": rule_id,
                    "technology": technology,
                    "confidence": detection.confidence.value,
                },
                raw_evidence={"supporting_finding_ids": sorted(detection.supporting_ids)},
                source_url=detection.source_url,
                retrieved_at=now,
                confidence=detection.confidence,
                fingerprint=compute_fingerprint("technology", "tech.inference", {"target": target, "rule_id": rule_id, "technology": technology}),
            )
        )
    return results
