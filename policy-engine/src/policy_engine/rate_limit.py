"""Token-bucket rate limiter. Stdlib only.

Algorithm and field shape mirror agent_os.policies.rate_limiting so a host
that already speaks `RateLimitConfig(capacity=, refill_rate=)` can drop
this in unchanged. Refill is on every call via `elapsed * refill_rate`,
capped at `capacity`. All state mutations are guarded by `threading.Lock`.
"""

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RateLimitConfig:
    capacity: float
    refill_rate: float
    initial_tokens: float | None = None

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError("capacity must be > 0")
        if self.refill_rate < 0:
            raise ValueError("refill_rate must be >= 0")
        if self.initial_tokens is not None and not (
            0 <= self.initial_tokens <= self.capacity
        ):
            raise ValueError("initial_tokens must be in [0, capacity]")


@dataclass
class TokenBucket:
    capacity: float
    tokens: float
    refill_rate: float
    last_refill: float = field(default_factory=time.monotonic)
    _lock: Any = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    @classmethod
    def from_config(cls, config: RateLimitConfig) -> "TokenBucket":
        initial = (
            config.initial_tokens if config.initial_tokens is not None else config.capacity
        )
        return cls(
            capacity=config.capacity,
            tokens=initial,
            refill_rate=config.refill_rate,
        )

    def _refill_locked(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        if elapsed > 0 and self.refill_rate > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def consume(self, tokens: float = 1.0) -> bool:
        with self._lock:
            self._refill_locked()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    @property
    def available(self) -> float:
        with self._lock:
            self._refill_locked()
            return self.tokens

    def time_until_available(self, tokens: float = 1.0) -> float:
        with self._lock:
            self._refill_locked()
            if self.tokens >= tokens:
                return 0.0
            if self.refill_rate <= 0:
                return math.inf
            return (tokens - self.tokens) / self.refill_rate

    def reset(self, tokens: float | None = None) -> None:
        with self._lock:
            self.tokens = self.capacity if tokens is None else min(tokens, self.capacity)
            self.last_refill = time.monotonic()
