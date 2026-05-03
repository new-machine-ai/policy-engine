# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Retry utilities with attempt and elapsed-time limits."""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Retry policy for sync and async call wrappers."""

    max_attempts: int = 3
    backoff_base: float = 1.0
    max_elapsed_seconds: float | None = None
    exceptions: Sequence[type[BaseException]] = (Exception,)
    raise_exhausted: bool = True

    def __post_init__(self) -> None:
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if self.backoff_base < 0:
            raise ValueError("backoff_base must be non-negative")
        if self.max_elapsed_seconds is not None and self.max_elapsed_seconds < 0:
            raise ValueError("max_elapsed_seconds must be non-negative")
        if not self.exceptions:
            raise ValueError("exceptions must not be empty")


@dataclass(frozen=True)
class RetryEvent:
    """One retry event."""

    attempt: int
    delay_seconds: float
    exception_type: str
    message: str

    def to_dict(self) -> dict[str, int | float | str]:
        return {
            "attempt": self.attempt,
            "delay_seconds": self.delay_seconds,
            "exception_type": self.exception_type,
            "message": self.message,
        }


@dataclass
class RetryState:
    """Mutable state collected during a retry run."""

    attempts: int = 0
    events: list[RetryEvent] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)
    last_exception: BaseException | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "attempts": self.attempts,
            "events": [event.to_dict() for event in self.events],
            "elapsed_seconds": round(time.monotonic() - self.started_at, 6),
            "last_exception": type(self.last_exception).__name__ if self.last_exception else None,
        }


class RetryExhausted(Exception):
    """Raised when a retry policy exhausts attempts or elapsed time."""

    def __init__(self, state: RetryState, last_exception: BaseException) -> None:
        self.state = state
        self.last_exception = last_exception
        super().__init__(f"retry exhausted after {state.attempts} attempt(s): {last_exception}")


def retry(
    max_attempts: int = 3,
    backoff_base: float = 1.0,
    exceptions: Sequence[type[BaseException]] = (Exception,),
    on_retry: Callable[[RetryEvent], None] | None = None,
    max_elapsed_seconds: float | None = None,
    raise_exhausted: bool = True,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Retry sync or async functions with exponential backoff."""

    policy = RetryPolicy(
        max_attempts=max_attempts,
        backoff_base=backoff_base,
        max_elapsed_seconds=max_elapsed_seconds,
        exceptions=exceptions,
        raise_exhausted=raise_exhausted,
    )

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                state = RetryState()
                for attempt in range(1, policy.max_attempts + 1):
                    state.attempts = attempt
                    try:
                        return await func(*args, **kwargs)
                    except tuple(policy.exceptions) as exc:
                        state.last_exception = exc
                        if _exhausted(policy, state, attempt):
                            _raise_or_reraise(policy, state, exc)
                        delay = _delay(policy, attempt)
                        event = _event(attempt, delay, exc)
                        state.events.append(event)
                        if on_retry:
                            on_retry(event)
                        await asyncio.sleep(delay)
                assert state.last_exception is not None
                _raise_or_reraise(policy, state, state.last_exception)

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            state = RetryState()
            for attempt in range(1, policy.max_attempts + 1):
                state.attempts = attempt
                try:
                    return func(*args, **kwargs)
                except tuple(policy.exceptions) as exc:
                    state.last_exception = exc
                    if _exhausted(policy, state, attempt):
                        _raise_or_reraise(policy, state, exc)
                    delay = _delay(policy, attempt)
                    event = _event(attempt, delay, exc)
                    state.events.append(event)
                    if on_retry:
                        on_retry(event)
                    time.sleep(delay)
            assert state.last_exception is not None
            _raise_or_reraise(policy, state, state.last_exception)

        return sync_wrapper

    return decorator


def _exhausted(policy: RetryPolicy, state: RetryState, attempt: int) -> bool:
    if attempt >= policy.max_attempts:
        return True
    if policy.max_elapsed_seconds is not None:
        return (time.monotonic() - state.started_at) >= policy.max_elapsed_seconds
    return False


def _delay(policy: RetryPolicy, attempt: int) -> float:
    return policy.backoff_base * (2 ** (attempt - 1))


def _event(attempt: int, delay: float, exc: BaseException) -> RetryEvent:
    return RetryEvent(
        attempt=attempt,
        delay_seconds=delay,
        exception_type=type(exc).__name__,
        message=str(exc),
    )


def _raise_or_reraise(policy: RetryPolicy, state: RetryState, exc: BaseException) -> None:
    if policy.raise_exhausted:
        raise RetryExhausted(state, exc) from exc
    raise exc
