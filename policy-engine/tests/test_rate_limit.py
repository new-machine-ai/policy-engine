"""Unit tests for the TokenBucket rate limiter and its kernel integration."""

import math
import sys
import threading
import time
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from policy_engine import (  # noqa: E402
    BaseKernel,
    GovernancePolicy,
    PolicyRequest,
    RateLimitConfig,
    TokenBucket,
)


def test_config_validates_capacity() -> None:
    with pytest.raises(ValueError, match="capacity must be > 0"):
        RateLimitConfig(capacity=0, refill_rate=1.0)


def test_config_validates_refill_rate() -> None:
    with pytest.raises(ValueError, match="refill_rate must be >= 0"):
        RateLimitConfig(capacity=5, refill_rate=-1.0)


def test_config_validates_initial_tokens_range() -> None:
    with pytest.raises(ValueError, match="initial_tokens"):
        RateLimitConfig(capacity=5, refill_rate=1.0, initial_tokens=10)


def test_bucket_starts_full_by_default() -> None:
    bucket = TokenBucket.from_config(RateLimitConfig(capacity=5, refill_rate=1.0))
    assert bucket.available == 5.0


def test_bucket_honors_initial_tokens() -> None:
    bucket = TokenBucket.from_config(
        RateLimitConfig(capacity=5, refill_rate=1.0, initial_tokens=2)
    )
    # `available` refills before returning, so allow tiny drift from elapsed wall time
    assert bucket.available == pytest.approx(2.0, abs=0.01)


def test_consume_drains_then_blocks() -> None:
    bucket = TokenBucket.from_config(RateLimitConfig(capacity=3, refill_rate=0))
    assert bucket.consume() is True
    assert bucket.consume() is True
    assert bucket.consume() is True
    assert bucket.consume() is False


def test_consume_refills_over_time() -> None:
    bucket = TokenBucket.from_config(RateLimitConfig(capacity=2, refill_rate=10.0))
    assert bucket.consume() is True
    assert bucket.consume() is True
    assert bucket.consume() is False
    time.sleep(0.15)  # refill_rate=10 -> ~1.5 tokens after 150ms
    assert bucket.consume() is True


def test_time_until_available_zero_when_ready() -> None:
    bucket = TokenBucket.from_config(RateLimitConfig(capacity=1, refill_rate=1.0))
    assert bucket.time_until_available() == 0.0


def test_time_until_available_inf_when_no_refill() -> None:
    bucket = TokenBucket.from_config(RateLimitConfig(capacity=1, refill_rate=0))
    bucket.consume()
    assert bucket.time_until_available() == math.inf


def test_reset_restores_capacity() -> None:
    bucket = TokenBucket.from_config(RateLimitConfig(capacity=3, refill_rate=0))
    bucket.consume()
    bucket.consume()
    bucket.reset()
    assert bucket.available == 3.0


def test_consume_is_thread_safe() -> None:
    bucket = TokenBucket.from_config(RateLimitConfig(capacity=100, refill_rate=0))
    successes = []

    def worker() -> None:
        for _ in range(20):
            if bucket.consume():
                successes.append(1)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(successes) == 100  # exactly capacity, no double-counting


def test_kernel_creates_bucket_when_policy_has_rate_limit() -> None:
    policy = GovernancePolicy(
        name="rl",
        rate_limit=RateLimitConfig(capacity=2, refill_rate=0),
    )
    kernel = BaseKernel(policy)
    ctx = kernel.create_context("rl")
    assert ctx.rate_bucket is not None
    assert ctx.rate_bucket.available == 2.0


def test_kernel_omits_bucket_when_policy_has_none() -> None:
    kernel = BaseKernel(GovernancePolicy(name="no-rl"))
    ctx = kernel.create_context("no-rl")
    assert ctx.rate_bucket is None


def test_kernel_blocks_when_bucket_empty() -> None:
    policy = GovernancePolicy(
        name="rl",
        max_tool_calls=100,
        rate_limit=RateLimitConfig(capacity=2, refill_rate=0),
    )
    kernel = BaseKernel(policy)
    ctx = kernel.create_context("rl")

    assert kernel.evaluate(ctx, PolicyRequest(payload="a")).allowed is True
    assert kernel.evaluate(ctx, PolicyRequest(payload="b")).allowed is True
    decision = kernel.evaluate(ctx, PolicyRequest(payload="c"))
    assert decision.allowed is False
    assert decision.reason.startswith("rate_limited:wait_")


def test_rate_limit_does_not_consume_token_on_other_denials() -> None:
    policy = GovernancePolicy(
        name="rl",
        blocked_patterns=["DROP TABLE"],
        rate_limit=RateLimitConfig(capacity=2, refill_rate=0),
    )
    kernel = BaseKernel(policy)
    ctx = kernel.create_context("rl")

    # Pattern-blocked call should NOT consume a token
    blocked = kernel.evaluate(ctx, PolicyRequest(payload="DROP TABLE x"))
    assert blocked.allowed is False
    assert ctx.rate_bucket.available == 2.0

    # Both tokens still available for legitimate calls
    assert kernel.evaluate(ctx, PolicyRequest(payload="ok")).allowed is True
    assert kernel.evaluate(ctx, PolicyRequest(payload="ok")).allowed is True
    assert kernel.evaluate(ctx, PolicyRequest(payload="ok")).allowed is False
