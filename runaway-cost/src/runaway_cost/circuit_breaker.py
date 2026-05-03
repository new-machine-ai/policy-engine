# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Circuit breaker and cascade detection primitives."""

from __future__ import annotations

import inspect
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class CircuitState(str, Enum):
    """Circuit breaker state."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when a call is attempted on an open circuit."""

    def __init__(self, agent_id: str, retry_after: float) -> None:
        self.agent_id = agent_id
        self.retry_after = retry_after
        super().__init__(f"circuit open for agent {agent_id!r}; retry after {retry_after:.3f}s")


@dataclass(frozen=True)
class CircuitBreakerConfig:
    """Configuration for a circuit breaker."""

    failure_threshold: int = 5
    recovery_timeout_seconds: float = 30.0
    half_open_max_calls: int = 1

    def __post_init__(self) -> None:
        if self.failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if self.recovery_timeout_seconds < 0:
            raise ValueError("recovery_timeout_seconds must be non-negative")
        if self.half_open_max_calls <= 0:
            raise ValueError("half_open_max_calls must be positive")

    @property
    def reset_timeout_seconds(self) -> float:
        return self.recovery_timeout_seconds


class CircuitBreaker:
    """Thread-safe circuit breaker with sync and async call support."""

    def __init__(
        self,
        agent_id: str = "default",
        config: CircuitBreakerConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.agent_id = agent_id
        self.config = config or CircuitBreakerConfig()
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        return self.get_state().value

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def success_count(self) -> int:
        return self._success_count

    def get_state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    def retry_after(self) -> float:
        with self._lock:
            self._maybe_transition_to_half_open()
            if self._state is CircuitState.OPEN:
                return self._time_until_recovery()
            return 0.0

    def call(self, func: Any, *args: Any, fallback: Any = None, **kwargs: Any) -> Any:
        retry_after = self._prepare_call()
        if retry_after is not None:
            if fallback is not None:
                return fallback
            raise CircuitOpenError(self.agent_id, retry_after)
        try:
            result = func(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        if inspect.isawaitable(result):
            async def _await_result() -> Any:
                try:
                    value = await result
                except Exception:
                    self.record_failure()
                    raise
                self.record_success()
                return value

            return _await_result()
        self.record_success()
        return result

    def record_success(self) -> None:
        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._transition(CircuitState.CLOSED)
            self._failure_count = 0
            self._success_count += 1
            self._half_open_calls = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = self._clock()
            if self._state is CircuitState.HALF_OPEN:
                self._transition(CircuitState.OPEN)
                self._half_open_calls = 0
            elif self._failure_count >= self.config.failure_threshold:
                self._transition(CircuitState.OPEN)

    def reset(self) -> None:
        with self._lock:
            self._transition(CircuitState.CLOSED)
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._last_failure_time = 0.0

    def _prepare_call(self) -> float | None:
        with self._lock:
            self._maybe_transition_to_half_open()
            if self._state is CircuitState.OPEN:
                return self._time_until_recovery()
            if self._state is CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    return self._time_until_recovery()
                self._half_open_calls += 1
            return None

    def _maybe_transition_to_half_open(self) -> None:
        if self._state is CircuitState.OPEN:
            elapsed = self._clock() - self._last_failure_time
            if elapsed >= self.config.recovery_timeout_seconds:
                self._transition(CircuitState.HALF_OPEN)

    def _transition(self, new_state: CircuitState) -> None:
        self._state = new_state
        if new_state is CircuitState.HALF_OPEN:
            self._half_open_calls = 0

    def _time_until_recovery(self) -> float:
        elapsed = self._clock() - self._last_failure_time
        return max(0.0, self.config.recovery_timeout_seconds - elapsed)


class CascadeDetector:
    """Detect cascading failures across multiple agents."""

    def __init__(
        self,
        agents: list[str],
        cascade_threshold: int = 3,
        config: CircuitBreakerConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if cascade_threshold <= 0:
            raise ValueError("cascade_threshold must be positive")
        self.cascade_threshold = cascade_threshold
        self._breakers = {
            agent_id: CircuitBreaker(agent_id, config, clock=clock)
            for agent_id in agents
        }

    def get_breaker(self, agent_id: str) -> CircuitBreaker | None:
        return self._breakers.get(agent_id)

    def check_cascade(self) -> bool:
        return len(self.get_affected_agents()) >= self.cascade_threshold

    def get_affected_agents(self) -> list[str]:
        return [
            agent_id
            for agent_id, breaker in self._breakers.items()
            if breaker.get_state() is CircuitState.OPEN
        ]

    def reset_all(self) -> None:
        for breaker in self._breakers.values():
            breaker.reset()
