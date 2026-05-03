from __future__ import annotations

import asyncio
import importlib

import pytest

from runaway_cost import (
    CascadeDetector,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    CircuitState,
    RetryExhausted,
    retry,
)


def test_circuit_breaker_closed_open_half_open_closed_and_retry_after():
    now = [0.0]
    breaker = CircuitBreaker(
        "agent-1",
        CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=5),
        clock=lambda: now[0],
    )

    assert breaker.get_state() is CircuitState.CLOSED
    breaker.record_failure()
    assert breaker.get_state() is CircuitState.CLOSED
    breaker.record_failure()
    assert breaker.get_state() is CircuitState.OPEN
    assert breaker.retry_after() == 5.0

    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: "ok")
    assert breaker.call(lambda: "ok", fallback="fallback") == "fallback"

    now[0] = 5.0
    assert breaker.get_state() is CircuitState.HALF_OPEN
    assert breaker.call(lambda: "ok") == "ok"
    assert breaker.get_state() is CircuitState.CLOSED

    breaker.reset()
    assert breaker.failure_count == 0
    assert breaker.success_count == 0


def test_circuit_breaker_records_sync_and_async_call_failures():
    breaker = CircuitBreaker("agent-1", CircuitBreakerConfig(failure_threshold=1))

    def fail_sync() -> None:
        raise RuntimeError("failed")

    with pytest.raises(RuntimeError):
        breaker.call(fail_sync)
    assert breaker.get_state() is CircuitState.OPEN

    breaker.reset()

    async def fail_async() -> None:
        raise RuntimeError("failed")

    with pytest.raises(RuntimeError):
        asyncio.run(breaker.call(fail_async))
    assert breaker.get_state() is CircuitState.OPEN


def test_cascade_detector_threshold_and_reset():
    detector = CascadeDetector(
        ["a", "b", "c"],
        cascade_threshold=2,
        config=CircuitBreakerConfig(failure_threshold=1),
    )

    detector.get_breaker("a").record_failure()
    assert not detector.check_cascade()
    detector.get_breaker("b").record_failure()
    assert detector.check_cascade()
    assert detector.get_affected_agents() == ["a", "b"]

    detector.reset_all()
    assert detector.get_affected_agents() == []


def test_retry_sync_success_exhaustion_selected_exception_and_max_elapsed(monkeypatch):
    retry_module = importlib.import_module("runaway_cost.retry")
    monkeypatch.setattr(retry_module.time, "sleep", lambda _seconds: None)
    events = []
    attempts = {"count": 0}

    @retry(max_attempts=3, backoff_base=0.0, on_retry=events.append)
    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("temporary")
        return "ok"

    assert flaky() == "ok"
    assert len(events) == 1
    assert events[0].attempt == 1

    @retry(max_attempts=2, backoff_base=0.0)
    def always_fails() -> None:
        raise RuntimeError("nope")

    with pytest.raises(RetryExhausted) as exc_info:
        always_fails()
    assert exc_info.value.state.attempts == 2

    @retry(max_attempts=3, exceptions=(ValueError,), backoff_base=0.0)
    def uncaught() -> None:
        raise KeyError("outside policy")

    with pytest.raises(KeyError):
        uncaught()

    @retry(max_attempts=3, max_elapsed_seconds=0.0, backoff_base=0.0)
    def elapsed() -> None:
        raise RuntimeError("elapsed")

    with pytest.raises(RetryExhausted) as elapsed_info:
        elapsed()
    assert elapsed_info.value.state.attempts == 1


def test_retry_async(monkeypatch):
    async def no_sleep(_seconds: float) -> None:
        return None

    retry_module = importlib.import_module("runaway_cost.retry")
    monkeypatch.setattr(retry_module.asyncio, "sleep", no_sleep)
    attempts = {"count": 0}

    @retry(max_attempts=3, backoff_base=0.0)
    async def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("temporary")
        return "ok"

    assert asyncio.run(flaky()) == "ok"
