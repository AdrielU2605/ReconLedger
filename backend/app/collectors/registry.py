"""The collector registry (PRD FR-02): adding a collector means registering it
here, never modifying orchestration logic in app/jobs/runner.py.
"""
from __future__ import annotations

from app.collectors import crtsh, dns_doh, rdap
from app.collectors.base import Collector
from app.models.enums import TargetType


class CollectorRegistry:
    def __init__(self) -> None:
        self._collectors: dict[str, Collector] = {}

    def register(self, collector: Collector, *, allow_test_only: bool = False) -> None:
        if getattr(collector.metadata, "test_only", False) and not allow_test_only:
            raise RuntimeError(
                f"Refusing to register test-only collector {collector.metadata.name!r}. "
                "Test fixtures must build their own CollectorRegistry() and pass "
                "allow_test_only=True explicitly - they must never be registered on "
                "the shared production registry returned by get_production_registry()."
            )
        if collector.metadata.name in self._collectors:
            raise ValueError(f"Collector {collector.metadata.name!r} is already registered.")
        self._collectors[collector.metadata.name] = collector

    def get(self, name: str) -> Collector:
        try:
            return self._collectors[name]
        except KeyError as exc:
            raise KeyError(f"No collector named {name!r} is registered.") from exc

    def all(self) -> list[Collector]:
        return list(self._collectors.values())

    def for_target_type(self, target_type: TargetType) -> list[Collector]:
        return [c for c in self._collectors.values() if target_type in c.metadata.supported_targets]


def _register_real_collectors(registry: CollectorRegistry) -> None:
    """The single, explicit place real collectors are wired in. Nothing in
    this function ever imports from the tests/ package."""
    registry.register(rdap)
    registry.register(dns_doh)
    registry.register(crtsh)


_production_registry: CollectorRegistry | None = None


def get_production_registry() -> CollectorRegistry:
    global _production_registry
    if _production_registry is None:
        _production_registry = CollectorRegistry()
        _register_real_collectors(_production_registry)
    return _production_registry
