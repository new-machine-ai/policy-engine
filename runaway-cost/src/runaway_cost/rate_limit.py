# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Rate limiting primitives for runaway-cost control."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RateLimitExceeded(Exception):
    """Raised when a rate-limited operation cannot proceed."""

    def __init__(self, message: str, *, wait_seconds: float = 0.0) -> None:
        self.wait_seconds = wait_seconds
        super().__init__(message)


@dataclass(frozen=True)
class RateLimitConfig:
    """Token-bucket configuration."""

    capacity: float
    refill_rate: float
    initial_tokens: float | None = None

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError("capacity must be positive")
        if self.refill_rate < 0:
            raise ValueError("refill_rate must be non-negative")
        if self.initial_tokens is not None and not 0 <= self.initial_tokens <= self.capacity:
            raise ValueError("initial_tokens must be between 0 and capacity")

    @property
    def rate(self) -> float:
        return self.refill_rate


@dataclass
class TokenBucket:
    """Thread-safe token bucket."""

    capacity: float
    tokens: float
    refill_rate: float
    last_refill: float = field(default_factory=time.monotonic)
    clock: Callable[[], float] = time.monotonic
    _lock: Any = field(default_factory=threading.Lock, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError("capacity must be positive")
        if self.refill_rate < 0:
            raise ValueError("refill_rate must be non-negative")
        if not 0 <= self.tokens <= self.capacity:
            raise ValueError("tokens must be between 0 and capacity")

    @classmethod
    def from_config(cls, config: RateLimitConfig, *, clock: Callable[[], float] = time.monotonic) -> "TokenBucket":
        initial_tokens = config.capacity if config.initial_tokens is None else config.initial_tokens
        return cls(
            capacity=config.capacity,
            tokens=initial_tokens,
            refill_rate=config.refill_rate,
            clock=clock,
            last_refill=clock(),
        )

    def consume(self, tokens: float = 1.0) -> bool:
        if tokens <= 0:
            raise ValueError("tokens must be positive")
        with self._lock:
            self._refill_unlocked()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    @property
    def available(self) -> float:
        with self._lock:
            self._refill_unlocked()
            return self.tokens

    def time_until_available(self, tokens: float = 1.0) -> float:
        if tokens <= 0:
            raise ValueError("tokens must be positive")
        with self._lock:
            self._refill_unlocked()
            if self.tokens >= tokens:
                return 0.0
            if self.refill_rate == 0:
                return float("inf")
            return (tokens - self.tokens) / self.refill_rate

    def reset(self, tokens: float | None = None) -> None:
        target = self.capacity if tokens is None else tokens
        if not 0 <= target <= self.capacity:
            raise ValueError("tokens must be between 0 and capacity")
        with self._lock:
            self.tokens = target
            self.last_refill = self.clock()

    def _refill_unlocked(self) -> None:
        now = self.clock()
        elapsed = now - self.last_refill
        if elapsed <= 0:
            return
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now


@dataclass(frozen=True)
class RateLimitStatus:
    """Snapshot of rate-limit state."""

    allowed: bool
    remaining_calls: int
    reset_at: float
    wait_seconds: float

    def to_dict(self) -> dict[str, float | int | bool]:
        return {
            "allowed": self.allowed,
            "remaining_calls": self.remaining_calls,
            "reset_at": self.reset_at,
            "wait_seconds": self.wait_seconds,
        }


class RateLimiter:
    """Token-bucket rate limiter for tool calls."""

    _GLOBAL_KEY = "__global__"

    def __init__(
        self,
        max_calls: int = 10,
        time_window: float = 60.0,
        per_agent: bool = True,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_calls <= 0:
            raise ValueError("max_calls must be positive")
        if time_window <= 0:
            raise ValueError("time_window must be positive")
        self._max_calls = max_calls
        self._time_window = float(time_window)
        self._per_agent = per_agent
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, TokenBucket] = {}

    def allow(self, agent_id: str) -> bool:
        with self._lock:
            return self._get_bucket(self._key(agent_id)).consume()

    def check(self, agent_id: str) -> RateLimitStatus:
        with self._lock:
            bucket = self._get_bucket(self._key(agent_id))
            remaining = int(bucket.available)
            wait = bucket.time_until_available()
            return RateLimitStatus(
                allowed=remaining >= 1,
                remaining_calls=remaining,
                reset_at=self._clock() + self._time_window,
                wait_seconds=wait,
            )

    def wait_time(self, agent_id: str) -> float:
        return self.check(agent_id).wait_seconds

    def reset(self, agent_id: str) -> None:
        with self._lock:
            self._buckets.pop(self._key(agent_id), None)

    def _key(self, agent_id: str) -> str:
        return _normalize_agent_id(agent_id) if self._per_agent else self._GLOBAL_KEY

    def _get_bucket(self, key: str) -> TokenBucket:
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = TokenBucket(
                capacity=float(self._max_calls),
                tokens=float(self._max_calls),
                refill_rate=self._max_calls / self._time_window,
                clock=self._clock,
                last_refill=self._clock(),
            )
            self._buckets[key] = bucket
        return bucket


class SlidingWindowRateLimiter:
    """Per-agent sliding-window limiter for tool or model calls."""

    def __init__(
        self,
        *,
        max_calls_per_window: int = 100,
        window_size: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_calls_per_window <= 0:
            raise ValueError("max_calls_per_window must be positive")
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        self.max_calls_per_window = max_calls_per_window
        self.window_size = float(window_size)
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, list[float]] = {}

    def try_acquire(self, agent_id: str) -> bool:
        key = _normalize_agent_id(agent_id)
        with self._lock:
            bucket = self._bucket(key)
            self._prune(bucket)
            if len(bucket) >= self.max_calls_per_window:
                return False
            bucket.append(self._clock())
            return True

    def get_remaining_budget(self, agent_id: str) -> int:
        key = _normalize_agent_id(agent_id)
        with self._lock:
            bucket = self._bucket(key)
            self._prune(bucket)
            return max(0, self.max_calls_per_window - len(bucket))

    def get_call_count(self, agent_id: str) -> int:
        key = _normalize_agent_id(agent_id)
        with self._lock:
            bucket = self._bucket(key)
            self._prune(bucket)
            return len(bucket)

    def cleanup_expired(self) -> int:
        removed = 0
        with self._lock:
            for bucket in self._buckets.values():
                before = len(bucket)
                self._prune(bucket)
                removed += before - len(bucket)
        return removed

    def reset(self, agent_id: str) -> None:
        with self._lock:
            self._buckets.pop(_normalize_agent_id(agent_id), None)

    def reset_all(self) -> None:
        with self._lock:
            self._buckets.clear()

    def _bucket(self, key: str) -> list[float]:
        return self._buckets.setdefault(key, [])

    def _prune(self, bucket: list[float]) -> None:
        cutoff = self._clock() - self.window_size
        while bucket and bucket[0] <= cutoff:
            bucket.pop(0)


class ExecutionRing(str, Enum):
    """Runtime ring used for per-agent rate limits."""

    RING_0_ROOT = "ring_0_root"
    RING_1_PRIVILEGED = "ring_1_privileged"
    RING_2_STANDARD = "ring_2_standard"
    RING_3_SANDBOX = "ring_3_sandbox"


DEFAULT_RING_LIMITS: dict[ExecutionRing, tuple[float, float]] = {
    ExecutionRing.RING_0_ROOT: (20.0, 100.0),
    ExecutionRing.RING_1_PRIVILEGED: (10.0, 50.0),
    ExecutionRing.RING_2_STANDARD: (5.0, 25.0),
    ExecutionRing.RING_3_SANDBOX: (1.0, 5.0),
}
RATE_LIMIT_FALLBACK = (1.0, 3.0)


@dataclass
class RateLimitStats:
    """Statistics for one agent/session bucket."""

    agent_did: str
    ring: ExecutionRing
    total_requests: int = 0
    rejected_requests: int = 0
    tokens_available: float = 0.0
    capacity: float = 0.0

    def to_dict(self) -> dict[str, str | int | float]:
        return {
            "agent_did": self.agent_did,
            "ring": self.ring.value,
            "total_requests": self.total_requests,
            "rejected_requests": self.rejected_requests,
            "tokens_available": round(self.tokens_available, 4),
            "capacity": self.capacity,
        }


class AgentRateLimiter:
    """Per-agent/per-session/per-ring token bucket limiter."""

    def __init__(
        self,
        ring_limits: dict[ExecutionRing, tuple[float, float]] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = ring_limits or dict(DEFAULT_RING_LIMITS)
        self._clock = clock
        self._buckets: dict[str, TokenBucket] = {}
        self._stats: dict[str, RateLimitStats] = {}

    def check(
        self,
        agent_did: str,
        session_id: str,
        ring: ExecutionRing | str,
        cost: float = 1.0,
    ) -> bool:
        if cost <= 0:
            raise ValueError("cost must be positive")
        ring_value = ExecutionRing(ring)
        key = self._key(agent_did, session_id)
        bucket = self._get_or_create_bucket(key, ring_value)
        stats = self._stats.setdefault(key, RateLimitStats(agent_did=agent_did, ring=ring_value))
        stats.total_requests += 1
        if not bucket.consume(cost):
            stats.rejected_requests += 1
            stats.tokens_available = bucket.available
            stats.capacity = bucket.capacity
            raise RateLimitExceeded(
                f"agent {agent_did} exceeded rate limit for {ring_value.value}",
                wait_seconds=bucket.time_until_available(cost),
            )
        stats.tokens_available = bucket.available
        stats.capacity = bucket.capacity
        return True

    def try_check(
        self,
        agent_did: str,
        session_id: str,
        ring: ExecutionRing | str,
        cost: float = 1.0,
    ) -> bool:
        try:
            return self.check(agent_did, session_id, ring, cost)
        except RateLimitExceeded:
            return False

    def update_ring(self, agent_did: str, session_id: str, new_ring: ExecutionRing | str) -> None:
        ring_value = ExecutionRing(new_ring)
        key = self._key(agent_did, session_id)
        rate, capacity = self._limits.get(ring_value, RATE_LIMIT_FALLBACK)
        self._buckets[key] = TokenBucket(
            capacity=capacity,
            tokens=capacity,
            refill_rate=rate,
            clock=self._clock,
            last_refill=self._clock(),
        )
        if key in self._stats:
            self._stats[key].ring = ring_value

    def get_stats(self, agent_did: str, session_id: str) -> RateLimitStats | None:
        key = self._key(agent_did, session_id)
        stats = self._stats.get(key)
        if stats is None:
            return None
        bucket = self._buckets.get(key)
        if bucket is not None:
            stats.tokens_available = bucket.available
            stats.capacity = bucket.capacity
        return stats

    @property
    def tracked_agents(self) -> int:
        return len(self._buckets)

    def _get_or_create_bucket(self, key: str, ring: ExecutionRing) -> TokenBucket:
        bucket = self._buckets.get(key)
        if bucket is None:
            rate, capacity = self._limits.get(ring, RATE_LIMIT_FALLBACK)
            bucket = TokenBucket(
                capacity=capacity,
                tokens=capacity,
                refill_rate=rate,
                clock=self._clock,
                last_refill=self._clock(),
            )
            self._buckets[key] = bucket
        return bucket

    @staticmethod
    def _key(agent_did: str, session_id: str) -> str:
        return f"{_normalize_agent_id(agent_did)}:{session_id}"


def _normalize_agent_id(agent_id: str) -> str:
    if not agent_id or not agent_id.strip():
        raise ValueError("agent_id must not be empty")
    return agent_id.casefold()
