from __future__ import annotations

from runaway_cost import CircuitBreaker, CircuitBreakerConfig


def main() -> None:
    now = [0.0]
    breaker = CircuitBreaker(
        "agent-1",
        CircuitBreakerConfig(failure_threshold=1, recovery_timeout_seconds=5),
        clock=lambda: now[0],
    )

    breaker.record_failure()
    print("opened:", breaker.get_state().value, "retry_after=", breaker.retry_after())
    now[0] = 5.0
    print("half-open:", breaker.get_state().value)
    breaker.record_success()
    print("closed:", breaker.get_state().value)


if __name__ == "__main__":
    main()
