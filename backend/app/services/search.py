"""UX-08 global search over a job's findings, backed by the findings_fts
FTS5 projection (migrated in 0001_initial).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def fts5_phrase_query(raw: str) -> str:
    """Wrap free-text user input as a single FTS5 phrase literal.

    FTS5's query syntax treats -, *, (, ", and column-name-like tokens
    specially; without this, arbitrary user input (e.g. a URL parameter
    containing a hyphen) can raise a SQLite syntax error instead of just
    not matching anything. Quoting as one phrase makes it safe and gives
    substring-of-words matching, which is what a search box should do.
    """
    escaped = raw.replace('"', '""')
    return f'"{escaped}"'


async def find_matching_finding_ids(session: AsyncSession, *, job_id: str, query: str) -> list[str]:
    result = await session.execute(
        text(
            """
            SELECT findings.id FROM findings
            JOIN findings_fts ON findings.rowid = findings_fts.rowid
            WHERE findings.job_id = :job_id AND findings_fts MATCH :query
            """
        ),
        {"job_id": job_id, "query": fts5_phrase_query(query)},
    )
    return [row[0] for row in result.all()]
