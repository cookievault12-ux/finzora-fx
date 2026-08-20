"""Tests for src/data/rate_limit.py — verified manually in the build sandbox
(pure stdlib, no install needed) before this file was written; see commit
history for that run's output."""

from __future__ import annotations

import time

from src.data.rate_limit import CircuitBreaker, TokenBucket


def test_token_bucket_allows_burst_up_to_capacity():
    bucket = TokenBucket(capacity=2, refill_per_second=10)
    start = time.monotonic()
    bucket.acquire()
    bucket.acquire()
    assert time.monotonic() - start < 0.05


def test_token_bucket_blocks_past_capacity():
    bucket = TokenBucket(capacity=2, refill_per_second=10)
    bucket.acquire()
    bucket.acquire()
    start = time.monotonic()
    bucket.acquire()
    assert time.monotonic() - start >= 0.08


def test_circuit_breaker_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, reset_after_seconds=0.2)
    assert cb.is_open is False
    for _ in range(3):
        cb.record_failure()
    assert cb.is_open is True


def test_circuit_breaker_half_opens_after_reset_window():
    cb = CircuitBreaker(failure_threshold=2, reset_after_seconds=0.1)
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open is True
    time.sleep(0.15)
    assert cb.is_open is False


def test_circuit_breaker_success_resets_failure_count():
    cb = CircuitBreaker(failure_threshold=3, reset_after_seconds=10)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open is False  # only 2 consecutive since the reset
