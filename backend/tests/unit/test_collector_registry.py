import pytest

from app.collectors.base import CachePolicy, CollectedFinding, CollectorContext, CollectorMetadata, RatePolicy
from app.collectors.registry import CollectorRegistry, get_production_registry
from app.models.enums import Category, TargetType


class _FakeCollector:
    def __init__(self, name: str = "fake", *, test_only: bool = True) -> None:
        self.metadata = CollectorMetadata(
            name=name,
            display_name="Fake",
            supported_targets=frozenset({TargetType.DOMAIN}),
            categories=frozenset({Category.NETWORK_FOOTPRINT}),
            required_credentials=(),
            provider_hosts=frozenset({"fake.example"}),
            key_help_url=None,
            rate_policy=RatePolicy(requests_per_period=1, period_seconds=1, burst=1, concurrency=1),
            cache_policy=CachePolicy(positive_ttl_seconds=60, negative_ttl_seconds=60, schema_version="1"),
            test_only=test_only,
        )

    async def run(self, context: CollectorContext) -> list[CollectedFinding]:
        return []


def test_test_only_collector_cannot_join_a_registry_without_explicit_flag() -> None:
    registry = CollectorRegistry()
    with pytest.raises(RuntimeError):
        registry.register(_FakeCollector())


def test_test_only_collector_can_join_a_registry_with_explicit_flag() -> None:
    registry = CollectorRegistry()
    registry.register(_FakeCollector(), allow_test_only=True)
    assert registry.get("fake") is not None


def test_production_registry_contains_no_test_only_collectors() -> None:
    """A durable guard: however many real collectors accumulate over the
    project's life, none of them may ever be test_only=True."""
    registry = get_production_registry()
    assert all(not collector.metadata.test_only for collector in registry.all())


def test_duplicate_registration_is_rejected() -> None:
    registry = CollectorRegistry()
    registry.register(_FakeCollector(name="dup"), allow_test_only=True)
    with pytest.raises(ValueError):
        registry.register(_FakeCollector(name="dup"), allow_test_only=True)


def test_unknown_collector_lookup_raises_key_error() -> None:
    registry = CollectorRegistry()
    with pytest.raises(KeyError):
        registry.get("does-not-exist")


def test_for_target_type_filters_by_supported_targets() -> None:
    registry = CollectorRegistry()
    registry.register(_FakeCollector(name="domain-only"), allow_test_only=True)
    assert registry.for_target_type(TargetType.DOMAIN) != []
    assert registry.for_target_type(TargetType.IP) == []
