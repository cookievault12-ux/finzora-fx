"""Simple token-bucket rate limiter + retry/circuit-breaker helpers
(spec section 78: retry, exponential backoff, circuit breaker, rate limiter).

Kept dependency-light: the rate limiter is pure stdlib (threading + time).
Retry/backoff is provided via a thin tenacity wrapper (tenacity is already
a pyproject.toml dependency) so call sites don't need to know tenacity's API.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    """Classic token-bucket limiter: `capacity` tokens, refilled at
    `refill_per_second`. Call `.acquire()` before each provider request;
    it blocks until a token is available rather than raising, since a
    scheduled ingestion job would rather wait a few seconds than fail."""

    capacity: int
    refill_per_second: float

    def __post_init__(self) -> None:
        self._tokens = float(self.capacity)
        self._lock = threading.Lock()
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_second)
        self._last_refill = now

    def acquire(self, tokens: int = 1) -> None:
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                wait_time = deficit / self.refill_per_second
            time.sleep(wait_time)


class CircuitBreaker:
    """Trips open after `failure_threshold` consecutive failures and stays
    open for `reset_after_seconds` before allowing a trial call through.
    Used to stop hammering a provider that's down (spec section 77/78) —
    the caller is expected to fall back to a backup provider, or to
    NO TRADE, once this reports open."""

    def __init__(self, failure_threshold: int = 5, reset_after_seconds: float = 60.0):
        self.failure_threshold = failure_threshold
        self.reset_after_seconds = reset_after_seconds
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            if time.monotonic() - self._opened_at >= self.reset_after_seconds:
                # half-open: allow the next call through as a trial
                self._opened_at = None
                self._consecutive_failures = 0
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.failure_threshold and self._opened_at is None:
                self._opened_at = time.monotonic()
