"""End-to-end API tests: real (migrated) SQLite, real FastAPI lifespan and
background worker loop, a fake in-process collector standing in for a real
provider. Sync TestClient + plain sync test functions - the worker loop runs
on its own background asyncio task inside the app's event loop thread, so
polling GET /api/jobs/{id} from a synchronous test is the natural way to
observe it finishing.
"""
from __future__ import annotations

import ipaddress
import time
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.collectors.base import CachePolicy, CollectedFinding, CollectorMetadata, RatePolicy
from app.collectors.registry import CollectorRegistry
from app.config import Settings
from app.main import create_app
from app.models.enums import Category, TargetType
from app.security.gateway import OutboundGateway
from app.security.network import StaticResolver

TERMINAL_STATUSES = {"completed", "completed_with_warnings", "failed", "canceled"}

GOOGLE_DOH_HOST = "dns.google"


def _fake_gateway_factory(settings: Settings) -> OutboundGateway:
    """Every job in these tests uses a domain target, so the runner always
    seeds its deny-list via a DoH bootstrap call to dns.google before the
    echo collector (which never touches the gateway itself) runs. That call
    must never reach the real network - not "usually blocked by
    --disable-socket", but structurally incapable of it, the same way every
    other test in this suite works.
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        # The gateway pins the connection to the resolved IP before this
        # inner transport ever sees the request, so request.url.host is
        # already the pinned address, not the logical hostname - check the
        # preserved Host header instead (see test_deny_list_seeding.py).
        if request.headers.get("host") == GOOGLE_DOH_HOST:
            return httpx.Response(200, json={"Answer": [{"data": "93.184.216.34"}]})
        raise AssertionError(f"unexpected provider request to {request.url} (host header: {request.headers.get('host')})")

    resolver = StaticResolver(table={GOOGLE_DOH_HOST: [ipaddress.ip_address("8.8.8.8")]})
    return OutboundGateway(transport=httpx.MockTransport(handler), resolver=resolver, settings=settings)


class _EchoCollector:
    def __init__(self) -> None:
        self.metadata = CollectorMetadata(
            name="echo",
            display_name="Echo",
            supported_targets=frozenset({TargetType.DOMAIN, TargetType.IP}),
            categories=frozenset({Category.NETWORK_FOOTPRINT}),
            required_credentials=(),
            provider_hosts=frozenset(),
            key_help_url=None,
            rate_policy=RatePolicy(requests_per_period=1, period_seconds=1, burst=1, concurrency=1),
            cache_policy=CachePolicy(positive_ttl_seconds=1, negative_ttl_seconds=1, schema_version="1"),
            test_only=True,
        )

    async def run(self, context) -> list[CollectedFinding]:
        return [
            CollectedFinding(
                category=Category.NETWORK_FOOTPRINT,
                kind="echo.finding",
                title="Echo finding",
                summary="summary",
                normalized_value={},
                raw_evidence={},
                source_url="https://provider.example/evidence",
                retrieved_at=datetime.now(timezone.utc),
                fingerprint="fp-echo",
            )
        ]


class _FailingCollector:
    def __init__(self) -> None:
        self.metadata = CollectorMetadata(
            name="failing",
            display_name="Failing",
            supported_targets=frozenset({TargetType.DOMAIN, TargetType.IP}),
            categories=frozenset({Category.NETWORK_FOOTPRINT}),
            required_credentials=(),
            provider_hosts=frozenset(),
            key_help_url=None,
            rate_policy=RatePolicy(requests_per_period=1, period_seconds=1, burst=1, concurrency=1),
            cache_policy=CachePolicy(positive_ttl_seconds=1, negative_ttl_seconds=1, schema_version="1"),
            test_only=True,
        )

    async def run(self, context) -> list[CollectedFinding]:
        raise RuntimeError("deliberately fails for warning_count coverage")


@pytest.fixture
def client(db_url: str, tmp_path):
    settings = Settings(_env_file=None, database_url=db_url, worker_lock_path=str(tmp_path / "worker.lock"))
    registry = CollectorRegistry()
    registry.register(_EchoCollector(), allow_test_only=True)
    registry.register(_FailingCollector(), allow_test_only=True)
    app = create_app(settings, registry=registry, gateway_factory=_fake_gateway_factory)
    with TestClient(app) as test_client:
        yield test_client


def _launch(client: TestClient, target: str = "example.com", *, attested: bool = True) -> dict:
    return client.post(
        "/api/jobs",
        json={"target": target, "selected_sources": ["echo"], "attestation_confirmed": attested},
    ).json()


def _wait_for_terminal(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in TERMINAL_STATUSES:
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not reach a terminal state within {timeout}s")


def test_sources_endpoint_lists_registered_collector(client: TestClient) -> None:
    resp = client.get("/api/sources")
    assert resp.status_code == 200
    assert "echo" in [s["name"] for s in resp.json()]


def test_create_job_runs_to_completion_and_persists_findings(client: TestClient) -> None:
    created = _launch(client)
    assert created["status"] == "queued"

    job = _wait_for_terminal(client, created["id"])
    assert job["status"] == "completed"
    assert job["collector_runs"][0]["status"] == "done"
    assert job["collector_runs"][0]["finding_count"] == 1

    export = client.get(f"/api/jobs/{job['id']}/export", params={"format": "json"})
    assert export.status_code == 200
    assert export.json()["findings"][0]["kind"] == "echo.finding"

    markdown = client.get(f"/api/jobs/{job['id']}/export", params={"format": "md", "mode": "summary"})
    assert markdown.status_code == 200
    assert "Echo finding" in markdown.text

    findings = client.get(f"/api/jobs/{job['id']}/findings")
    assert findings.status_code == 200
    assert findings.json()[0]["kind"] == "echo.finding"

    filtered = client.get(f"/api/jobs/{job['id']}/findings", params={"category": "human_layer"})
    assert filtered.status_code == 200
    assert filtered.json() == []  # the echo finding is network_footprint

    searched = client.get(f"/api/jobs/{job['id']}/findings", params={"q": "Echo finding"})
    assert searched.status_code == 200
    assert searched.json()[0]["kind"] == "echo.finding"

    no_match = client.get(f"/api/jobs/{job['id']}/findings", params={"q": "nothing-like-this"})
    assert no_match.status_code == 200
    assert no_match.json() == []

    # The echo collector doesn't produce ct.subdomain-kind evidence, so the
    # subdomain workspace should come back empty without erroring.
    subdomains = client.get(f"/api/jobs/{job['id']}/subdomains")
    assert subdomains.status_code == 200
    assert subdomains.json() == []

    csv_export = client.get(f"/api/jobs/{job['id']}/subdomains.csv")
    assert csv_export.status_code == 200
    assert csv_export.headers["content-type"].startswith("text/csv")
    assert csv_export.text.strip() == "subdomain,source_count,sources,first_seen_at,last_seen_at,wildcard,in_scope"


def test_findings_endpoint_404s_for_unknown_job(client: TestClient) -> None:
    resp = client.get("/api/jobs/does-not-exist/findings")
    assert resp.status_code == 404


def test_cors_preflight_allows_the_vite_dev_origin(client: TestClient) -> None:
    resp = client.options(
        "/api/jobs",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_create_job_rejects_unattested_request(client: TestClient) -> None:
    resp = client.post(
        "/api/jobs", json={"target": "example.com", "selected_sources": ["echo"], "attestation_confirmed": False}
    )
    assert resp.status_code == 422


def test_create_job_rejects_organization_target_with_release_1_1_explanation(client: TestClient) -> None:
    resp = client.post(
        "/api/jobs", json={"target": "Example Corp", "selected_sources": ["echo"], "attestation_confirmed": True}
    )
    assert resp.status_code == 422
    assert "release 1.1" in resp.json()["detail"]


def test_create_job_rejects_unknown_source(client: TestClient) -> None:
    resp = client.post(
        "/api/jobs",
        json={"target": "example.com", "selected_sources": ["not-a-real-source"], "attestation_confirmed": True},
    )
    assert resp.status_code == 422


def test_cross_origin_post_is_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/jobs",
        json={"target": "example.com", "selected_sources": ["echo"], "attestation_confirmed": True},
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403


def test_delete_job_removes_it_and_its_findings(client: TestClient) -> None:
    created = _launch(client)
    job = _wait_for_terminal(client, created["id"])

    delete_resp = client.delete(f"/api/jobs/{job['id']}")
    assert delete_resp.status_code == 204
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404


def test_diff_between_jobs_on_different_targets_is_rejected(client: TestClient) -> None:
    job_a = _wait_for_terminal(client, _launch(client, "example.com")["id"])
    job_b = _wait_for_terminal(client, _launch(client, "other-example.com")["id"])

    resp = client.get(f"/api/jobs/{job_a['id']}/diff", params={"against": job_b["id"]})
    assert resp.status_code == 409


def test_diff_between_repeat_runs_of_same_target_is_unchanged(client: TestClient) -> None:
    job_a = _wait_for_terminal(client, _launch(client, "example.com")["id"])
    job_b = _wait_for_terminal(client, _launch(client, "example.com")["id"])

    resp = client.get(f"/api/jobs/{job_b['id']}/diff", params={"against": job_a["id"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["unchanged_count"] == 1
    assert body["added"] == []
    assert body["removed"] == []


def test_sse_stream_reports_progress_and_terminates(client: TestClient) -> None:
    created = _launch(client)
    with client.stream("GET", f"/api/jobs/{created['id']}/events") as response:
        assert response.status_code == 200
        event_types = []
        for line in response.iter_lines():
            if line.startswith("data:"):
                import json

                event_types.append(json.loads(line[len("data:"):])["event_type"])
    assert "collector_started" in event_types
    assert "collector_finished" in event_types
    assert "job_finished" in event_types


def test_list_jobs_reports_a_warning_count_from_failed_collectors(client: TestClient) -> None:
    created = client.post(
        "/api/jobs",
        json={"target": "example.com", "selected_sources": ["echo", "failing"], "attestation_confirmed": True},
    ).json()
    job = _wait_for_terminal(client, created["id"])
    assert job["status"] == "completed_with_warnings"

    listing = client.get("/api/jobs").json()
    summary = next(j for j in listing if j["id"] == job["id"])
    assert summary["warning_count"] == 1


def test_list_jobs_reports_zero_warnings_for_a_clean_completion(client: TestClient) -> None:
    job = _wait_for_terminal(client, _launch(client)["id"])
    listing = client.get("/api/jobs").json()
    summary = next(j for j in listing if j["id"] == job["id"])
    assert summary["warning_count"] == 0
