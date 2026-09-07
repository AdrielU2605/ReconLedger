"""FR-06: stable finding identity for deduplication and diff.

fingerprint = SHA-256(collector, kind, canonical identity key). The identity
key is collector- and kind-specific and deliberately excludes mutable
attributes (e.g. a DNS record's TTL, or a certificate's "still valid" flag)
so that a genuine content change is visible as "changed" in a diff rather
than manufacturing a spurious added/removed pair every run.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def compute_fingerprint(collector: str, kind: str, identity: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"collector": collector, "kind": kind, "identity": identity},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
