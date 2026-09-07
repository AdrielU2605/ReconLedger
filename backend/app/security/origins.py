"""PRD 8.2: exact local frontend origins, JSON content types, and
state-changing request origin checks, to reduce localhost cross-site request
risks (a page in the browser making a fetch() against the local API).
"""
from __future__ import annotations

from fastapi import HTTPException, Request

# Vite's default dev-server origins on both loopback names. Updated once the
# production static build's serving origin is decided (CP4+).
ALLOWED_FRONTEND_ORIGINS: frozenset[str] = frozenset(
    {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }
)

_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


async def enforce_local_origin_and_content_type(request: Request) -> None:
    if request.method not in _STATE_CHANGING_METHODS:
        return

    origin = request.headers.get("origin")
    if origin is not None and origin not in ALLOWED_FRONTEND_ORIGINS:
        raise HTTPException(status_code=403, detail="Request origin is not allowed.")

    if request.method in _BODY_METHODS:
        content_length = request.headers.get("content-length")
        has_body = content_length is not None and content_length != "0"
        if has_body:
            content_type = request.headers.get("content-type", "")
            if not content_type.startswith("application/json"):
                raise HTTPException(status_code=415, detail="Content-Type must be application/json.")
