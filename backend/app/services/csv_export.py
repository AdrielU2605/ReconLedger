"""FR-11 / 8.2: formula-safe UTF-8 CSV export for the subdomain workspace.

A cell whose text begins with =, +, -, @, a tab, or a carriage return is
prefixed with a single quote before any spreadsheet application ever sees
it, so a subdomain or source name copied verbatim from provider evidence
can never execute as a formula when the analyst opens the export.
"""
from __future__ import annotations

import csv
import io

from app.services.subdomains import SubdomainRow

_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

CSV_HEADER = ["subdomain", "source_count", "sources", "first_seen_at", "last_seen_at", "wildcard", "in_scope"]


def _sanitize_cell(value: str) -> str:
    if value.startswith(_DANGEROUS_PREFIXES):
        return "'" + value
    return value


def build_subdomains_csv(rows: list[SubdomainRow]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for row in rows:
        writer.writerow(
            [
                _sanitize_cell(row.subdomain),
                str(row.source_count),
                _sanitize_cell(";".join(row.sources)),
                row.first_seen_at or "",
                row.last_seen_at or "",
                "true" if row.wildcard else "false",
                "true" if row.in_scope else "false",
            ]
        )
    return buffer.getvalue()
