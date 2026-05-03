from __future__ import annotations

from runaway_cost import AgentRateLimiter, ExecutionRing, RateLimitExceeded


def main() -> None:
    limiter = AgentRateLimiter(
        ring_limits={ExecutionRing.RING_2_STANDARD: (0.0, 1.0)}
    )

    print("first:", limiter.check("agent-1", "session-1", ExecutionRing.RING_2_STANDARD))
    try:
        limiter.check("agent-1", "session-1", ExecutionRing.RING_2_STANDARD)
    except RateLimitExceeded as exc:
        print("blocked:", exc)
    print("stats:", limiter.get_stats("agent-1", "session-1").to_dict())


if __name__ == "__main__":
    main()
