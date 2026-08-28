from __future__ import annotations

import logging

from imnot.engine.rate_limiter import RateLimiter


def test_fresh_bucket_allows_burst_up_to_capacity_then_rejects():
    limiter = RateLimiter()
    key = ("staylink", "reservations", "GET", "/reservations")
    capacity = 5

    for _ in range(capacity):
        allowed, retry_after = limiter.check(key, capacity, refill_per_second=1.0, now=0.0)
        assert allowed is True

    allowed, retry_after = limiter.check(key, capacity, refill_per_second=1.0, now=0.0)
    assert allowed is False
    assert retry_after > 0


def test_exceeding_capacity_returns_sane_retry_after():
    limiter = RateLimiter()
    key = ("bookingco", "rates", "GET", "/rates")
    capacity = 3
    refill_per_second = 0.5

    for _ in range(capacity):
        allowed, _ = limiter.check(key, capacity, refill_per_second, now=0.0)
        assert allowed is True

    allowed, retry_after = limiter.check(key, capacity, refill_per_second, now=0.0)
    assert allowed is False
    assert isinstance(retry_after, int)
    assert retry_after == 2


def test_refill_accrues_linearly_with_elapsed_time():
    limiter = RateLimiter()
    key = ("ratesync", "inventory", "GET", "/inventory")
    capacity = 10
    refill_per_second = 2.0

    for _ in range(capacity):
        allowed, _ = limiter.check(key, capacity, refill_per_second, now=0.0)
        assert allowed is True

    allowed, _ = limiter.check(key, capacity, refill_per_second, now=0.0)
    assert allowed is False

    elapsed = 3.0
    now = elapsed
    expected_tokens = elapsed * refill_per_second

    allowed_count = 0
    for _ in range(20):
        allowed, _ = limiter.check(key, capacity, refill_per_second, now=now)
        if allowed:
            allowed_count += 1
        else:
            break

    assert allowed_count == int(expected_tokens)


def test_refill_caps_at_capacity():
    limiter = RateLimiter()
    key = ("staylink", "availability", "GET", "/availability")
    capacity = 5
    refill_per_second = 1.0

    for _ in range(capacity):
        allowed, _ = limiter.check(key, capacity, refill_per_second, now=0.0)
        assert allowed is True

    huge_now = 10_000_000.0
    allowed_count = 0
    rejected_seen = False
    for _ in range(capacity + 1):
        allowed, _ = limiter.check(key, capacity, refill_per_second, now=huge_now)
        if allowed:
            allowed_count += 1
        else:
            rejected_seen = True

    assert allowed_count == capacity
    assert rejected_seen is True


def test_no_burst_at_window_boundary_like_naive_fixed_window():
    limiter = RateLimiter()
    key = ("staylink", "reservations", "GET", "/reservations")
    capacity = 60
    refill_per_second = 1.0

    first_batch_allowed = 0
    for _ in range(59):
        allowed, _ = limiter.check(key, capacity, refill_per_second, now=50.0)
        if allowed:
            first_batch_allowed += 1
    assert first_batch_allowed == 59

    now_values = [60.0 + i * (10.0 / 59) for i in range(60)]
    second_batch_allowed = 0
    for now in now_values:
        allowed, _ = limiter.check(key, capacity, refill_per_second, now=now)
        if allowed:
            second_batch_allowed += 1

    assert second_batch_allowed < 60
    assert second_batch_allowed <= 25


def test_check_logs_debug_record_on_rejection(caplog):
    limiter = RateLimiter()
    key = ("staylink", "reservations", "POST", "/reservations")
    capacity = 1

    with caplog.at_level(logging.DEBUG, logger="imnot.http"):
        limiter.check(key, capacity, refill_per_second=1.0, now=0.0)
        allowed, retry_after = limiter.check(key, capacity, refill_per_second=1.0, now=0.0)

    assert allowed is False

    matching = [r for r in caplog.records if r.name == "imnot.http" and r.levelno == logging.DEBUG]
    assert matching
    record = matching[-1]
    message = record.getMessage()
    assert str(key) in message
    assert str(retry_after) in message
