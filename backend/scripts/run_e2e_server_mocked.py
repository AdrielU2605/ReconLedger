"""Boots the real API against a throwaway SQLite database, with a scripted
(mocked) OutboundGateway - deterministic RDAP/DNS responses and a
deliberately-failing crt.sh - for Playwright's CP9 suite (happy path,
partial-provider failure, cached rerun, diff, keyboard nav, theme,
downloads: PRD 10.1). run_e2e_server.py's real-network boot already covers
UX-12 (client never contacts the assessed target) against genuine
evidence; these scenarios need repeatable data instead.
"""
from __future__ import annotations

import ipaddress
import os
import subprocess
import sys
from pathlib import Path

import httpx
import uvicorn

from app.collectors.registry import get_production_registry
from app.config import Settings
from app.main import create_app
from app.security.gateway import OutboundGateway
from app.security.network import StaticResolver

BACKEND_DIR = Path(__file__).resolve().parent.parent

RDAP_BOOTSTRAP = {"services": [[["com"], ["https://rdap.mocked-registry.test/"]]]}
RDAP_RECORD = {
    "handle": "2336799_DOMAIN_COM-VRSN",
    "ldhName": "EXAMPLE.COM",
    "status": ["client delete prohibited", "client transfer prohibited"],
    "nameservers": [{"ldhName": "A.IANA-SERVERS.NET"}, {"ldhName": "B.IANA-SERVERS.NET"}],
    "events": [{"eventAction": "registration", "eventDate": "1995-08-14T04:00:00Z"}],
    "entities": [
        {
            "roles": ["registrar"],
            "vcardArray": ["vcard", [["version", {}, "text", "4.0"], ["fn", {}, "text", "Example Registrar Inc."]]],
        }
    ],
}
EMPTY_DOH_RESPONSE = {"Status": 0, "Answer": []}


async def _handler(request: httpx.Request) -> httpx.Response:
    # The gateway pins the connection to the resolved IP before this inner
    # transport ever sees the request, so request.url.host is already the
    # pinned address - the preserved Host header carries the logical name.
    host = request.headers.get("host") or request.url.host
    if host == "data.iana.org":
        return httpx.Response(200, json=RDAP_BOOTSTRAP)
    if host == "rdap.mocked-registry.test":
        return httpx.Response(200, json=RDAP_RECORD)
    if host in ("dns.google", "cloudflare-dns.com"):
        return httpx.Response(200, json=EMPTY_DOH_RESPONSE)
    if host == "crt.sh":
        return httpx.Response(503, text="crt.sh is deliberately unavailable in this mocked e2e server")
    raise AssertionError(f"e2e mock has no scripted response for {request.url} (host={host!r})")


def _mocked_gateway_factory(settings: Settings) -> OutboundGateway:
    resolver = StaticResolver(
        table={
            "data.iana.org": [ipaddress.ip_address("93.184.216.40")],
            "rdap.mocked-registry.test": [ipaddress.ip_address("93.184.216.41")],
            "dns.google": [ipaddress.ip_address("8.8.8.8")],
            "cloudflare-dns.com": [ipaddress.ip_address("1.1.1.1")],
            "crt.sh": [ipaddress.ip_address("93.184.216.42")],
        }
    )
    return OutboundGateway(transport=httpx.MockTransport(_handler), resolver=resolver, settings=settings)


def main() -> None:
    db_path = BACKEND_DIR / "e2e-mocked.db"
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(db_path) + suffix)
        if candidate.exists():
            candidate.unlink()

    database_url = f"sqlite+aiosqlite:///{db_path}"
    env = os.environ.copy()
    env["RECONLEDGER_DATABASE_URL"] = database_url
    env["RECONLEDGER_WORKER_LOCK_PATH"] = str(BACKEND_DIR / "e2e-mocked-worker.lock")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND_DIR, env=env, check=True)

    settings = Settings(
        _env_file=None,
        database_url=database_url,
        worker_lock_path=str(BACKEND_DIR / "e2e-mocked-worker.lock"),
    )
    app = create_app(settings, registry=get_production_registry(), gateway_factory=_mocked_gateway_factory)
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
