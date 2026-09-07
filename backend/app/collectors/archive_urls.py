"""Shared URL normalization for the archive collectors (PRD FR-09): remove
fragments, preserve query strings as-is (no attempt to classify which query
keys are "meaningful" - that judgment call is left to the analyst, who sees
the full canonical URL either way), and deduplicate by canonical form.
"""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def canonicalize_archived_url(raw_url: str) -> str | None:
    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None

    netloc = parsed.netloc.lower()
    if parsed.scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[: -len(":80")]
    elif parsed.scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[: -len(":443")]

    path = parsed.path or "/"
    return urlunsplit((parsed.scheme, netloc, path, parsed.query, ""))


def host_of(canonical_url: str) -> str:
    return urlsplit(canonical_url).netloc


def is_in_scope(canonical_url: str, registrable_domain: str) -> bool:
    host = host_of(canonical_url)
    return host == registrable_domain or host.endswith("." + registrable_domain)


def extract_extension(canonical_url: str) -> str | None:
    path = urlsplit(canonical_url).path
    last_segment = path.rsplit("/", 1)[-1]
    if "." not in last_segment:
        return None
    ext = last_segment.rsplit(".", 1)[-1].lower()
    return ext if ext.isalnum() and 1 <= len(ext) <= 6 else None
