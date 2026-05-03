from __future__ import annotations

from runaway_cost import CascadeDetector, CircuitBreakerConfig


def main() -> None:
    detector = CascadeDetector(
        ["agent-a", "agent-b", "agent-c"],
        cascade_threshold=2,
        config=CircuitBreakerConfig(failure_threshold=1),
    )
    detector.get_breaker("agent-a").record_failure()
    detector.get_breaker("agent-b").record_failure()

    print("cascade:", detector.check_cascade())
    print("affected:", detector.get_affected_agents())


if __name__ == "__main__":
    main()
