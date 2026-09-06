"""FR-04: rate limiting and retry.

Independent per-source policies, bounded exponential backoff with full jitter,
Retry-After honored within the collector time budget, retries only on safe
idempotent reads, default 3 attempts / 0.5s base / 8s cap / configurable total
budget per collector.
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Callable

import httpx

_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    cap_delay_seconds: float = 8.0
    total_budget_seconds: float = 90.0


def compute_backoff_seconds(
    attempt: int, policy: RetryPolicy, rand: Callable[[], float] = random.random
) -> float:
    """Full-jitter exponential backoff: uniform(0, min(cap, base * 2**attempt))."""
    ceiling: float = min(policy.cap_delay_seconds, policy.base_delay_seconds * (2**attempt))
    return float(rand()) * ceiling


def should_retry(*, method: str, status_code: int | None, exception: Exception | None) -> bool:
    if method.upper() not in _IDEMPOTENT_METHODS:
        return False
    if exception is not None:
        return isinstance(exception, (httpx.TimeoutException, httpx.TransportError))
    if status_code is None:
        return False
    return status_code in _RETRYABLE_STATUS_CODES


def parse_retry_after(header_value: str | None) -> float | None:
    """Parse a Retry-After header value (seconds form only; HTTP-date form is rejected as unsafe
    to trust without a clock-skew policy, and providers in the MVP set use the seconds form)."""
    if header_value is None:
        return None
    try:
        seconds = float(header_value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


class RateLimiter:
    """A simple per-collector token bucket plus a concurrency cap.

    `requests_per_period` / `period_seconds` bound sustained throughput;
    `burst` allows short bursts up to that many immediate requests;
    `concurrency` bounds simultaneous in-flight requests to this collector.
    """

    def __init__(
        self,
        *,
        requests_per_period: float,
        period_seconds: float,
        burst: int,
        concurrency: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rate = requests_per_period / period_seconds
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._clock = clock
        self._last_refill = clock()
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(concurrency)

    async def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last_refill)
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    async def acquire(self) -> None:
        await self._semaphore.acquire()
        async with self._lock:
            await self._refill()
            while self._tokens < 1.0:
                wait_for = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait_for)
                await self._refill()
            self._tokens -= 1.0

    def release(self) -> None:
        self._semaphore.release()
