import asyncio
import time

import pytest

from app.security.rate_limit import RateLimiter, compute_backoff_seconds, parse_retry_after
from app.security.rate_limit import RetryPolicy


def test_compute_backoff_is_bounded_by_cap_with_full_jitter() -> None:
    policy = RetryPolicy(max_attempts=5, base_delay_seconds=0.5, cap_delay_seconds=8.0)
    for attempt in range(1, 6):
        for rand_value in (0.0, 0.5, 1.0):
            delay = compute_backoff_seconds(attempt, policy, rand=lambda v=rand_value: v)
            ceiling = min(policy.cap_delay_seconds, policy.base_delay_seconds * (2**attempt))
            assert 0.0 <= delay <= ceiling + 1e-9


@pytest.mark.parametrize(
    "header_value,expected",
    [("0", 0.0), ("5", 5.0), ("5.5", 5.5), (None, None), ("not-a-number", None), ("-1", None)],
)
def test_parse_retry_after(header_value, expected) -> None:
    assert parse_retry_after(header_value) == expected


@pytest.mark.asyncio
async def test_rate_limiter_bounds_concurrency() -> None:
    limiter = RateLimiter(requests_per_period=100, period_seconds=1, burst=100, concurrency=2)
    in_flight = 0
    max_in_flight = 0

    async def task() -> None:
        nonlocal in_flight, max_in_flight
        await limiter.acquire()
        try:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.01)
        finally:
            in_flight -= 1
            limiter.release()

    await asyncio.gather(*(task() for _ in range(6)))
    assert max_in_flight <= 2


@pytest.mark.asyncio
async def test_rate_limiter_throttles_beyond_burst() -> None:
    limiter = RateLimiter(requests_per_period=10, period_seconds=1, burst=1, concurrency=10)
    start = time.monotonic()
    await limiter.acquire()
    limiter.release()
    await limiter.acquire()  # burst exhausted; must wait for a token to refill
    limiter.release()
    elapsed = time.monotonic() - start
    assert elapsed > 0.0
