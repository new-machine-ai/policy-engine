from __future__ import annotations

import math

import pytest

from runaway_cost import (
    AgentRateLimiter,
    ExecutionRing,
    RateLimitConfig,
    RateLimitExceeded,
    RateLimiter,
    SlidingWindowRateLimiter,
    TokenBucket,
)


def test_token_bucket_validation_and_refill_wait_reset():
    with pytest.raises(ValueError):
        RateLimitConfig(capacity=0, refill_rate=1)
    with pytest.raises(ValueError):
        RateLimitConfig(capacity=1, refill_rate=-1)
    with pytest.raises(ValueError):
        RateLimitConfig(capacity=1, refill_rate=1, initial_tokens=2)

    now = [0.0]
    bucket = TokenBucket.from_config(
        RateLimitConfig(capacity=2, refill_rate=1, initial_tokens=1),
        clock=lambda: now[0],
    )

    assert bucket.consume()
    assert not bucket.consume()
    assert bucket.time_until_available() == 1.0

    now[0] += 0.5
    assert bucket.available == 0.5
    now[0] += 0.5
    assert bucket.consume()

    bucket.reset()
    assert bucket.available == 2
    bucket.reset(0)
    assert bucket.available == 0


def test_token_bucket_zero_refill_never_recovers():
    now = [0.0]
    bucket = TokenBucket.from_config(
        RateLimitConfig(capacity=1, refill_rate=0, initial_tokens=0),
        clock=lambda: now[0],
    )

    assert not bucket.consume()
    assert math.isinf(bucket.time_until_available())
    now[0] = 100.0
    assert bucket.available == 0


def test_rate_limiter_status_and_reset():
    now = [0.0]
    limiter = RateLimiter(max_calls=1, time_window=10, clock=lambda: now[0])

    assert limiter.allow("Agent-1")
    status = limiter.check("agent-1")
    assert not status.allowed
    assert status.remaining_calls == 0
    assert status.wait_seconds == 10.0

    limiter.reset("AGENT-1")
    assert limiter.check("agent-1").allowed


def test_sliding_window_allow_deny_cleanup_reset_and_normalized_ids():
    now = [0.0]
    limiter = SlidingWindowRateLimiter(max_calls_per_window=2, window_size=10, clock=lambda: now[0])

    assert limiter.try_acquire("Agent-1")
    assert limiter.try_acquire("agent-1")
    assert not limiter.try_acquire("AGENT-1")
    assert limiter.get_call_count("agent-1") == 2
    assert limiter.get_remaining_budget("agent-1") == 0

    now[0] = 11.0
    assert limiter.cleanup_expired() == 2
    assert limiter.try_acquire("agent-1")

    limiter.reset("AGENT-1")
    assert limiter.get_call_count("agent-1") == 0
    limiter.try_acquire("agent-1")
    limiter.reset_all()
    assert limiter.get_call_count("agent-1") == 0


def test_agent_rate_limiter_per_session_stats_ring_update_and_try_check():
    limiter = AgentRateLimiter(
        ring_limits={
            ExecutionRing.RING_2_STANDARD: (0.0, 1.0),
            ExecutionRing.RING_3_SANDBOX: (0.0, 2.0),
        }
    )

    assert limiter.check("agent-1", "session-1", ExecutionRing.RING_2_STANDARD)
    with pytest.raises(RateLimitExceeded) as exc_info:
        limiter.check("AGENT-1", "session-1", ExecutionRing.RING_2_STANDARD)
    assert math.isinf(exc_info.value.wait_seconds)
    assert not limiter.try_check("agent-1", "session-1", ExecutionRing.RING_2_STANDARD)

    stats = limiter.get_stats("agent-1", "session-1")
    assert stats is not None
    assert stats.total_requests == 3
    assert stats.rejected_requests == 2

    limiter.update_ring("agent-1", "session-1", ExecutionRing.RING_3_SANDBOX)
    stats = limiter.get_stats("agent-1", "session-1")
    assert stats is not None
    assert stats.ring is ExecutionRing.RING_3_SANDBOX
    assert limiter.check("agent-1", "session-1", ExecutionRing.RING_3_SANDBOX)
