"""Shared enums used by both the ORM layer (app/models/db.py) and the API
schemas (app/models/api.py), so the two never drift against each other."""
from __future__ import annotations

from enum import Enum


class TargetType(str, Enum):
    DOMAIN = "domain"
    IP = "ip"
    CIDR = "cidr"
    ORGANIZATION = "organization"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELED = "canceled"


TERMINAL_JOB_STATUSES = frozenset(
    {JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_WARNINGS, JobStatus.FAILED, JobStatus.CANCELED}
)


class CollectorStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED_NO_KEY = "skipped_no_key"
    NOT_APPLICABLE = "not_applicable"
    INTERRUPTED = "interrupted"


TERMINAL_COLLECTOR_STATUSES = frozenset(
    {
        CollectorStatus.DONE,
        CollectorStatus.FAILED,
        CollectorStatus.SKIPPED_NO_KEY,
        CollectorStatus.NOT_APPLICABLE,
    }
)
"""INTERRUPTED is deliberately not terminal: PRD FR-01 requires an interrupted
collector run to be resumed or completed-with-warnings on restart, not left as
a final state."""


class Category(str, Enum):
    NETWORK_FOOTPRINT = "network_footprint"
    TECHNOLOGY_STACK = "technology_stack"
    HUMAN_LAYER = "human_layer"
    LEAKED_DATA = "leaked_data"


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DiffState(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    INDETERMINATE = "indeterminate"
