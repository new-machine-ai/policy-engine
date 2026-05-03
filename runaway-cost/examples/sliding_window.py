from __future__ import annotations

from runaway_cost import SlidingWindowRateLimiter


def main() -> None:
    now = [0.0]
    limiter = SlidingWindowRateLimiter(max_calls_per_window=2, window_size=10, clock=lambda: now[0])

    print("first:", limiter.try_acquire("Agent-1"))
    print("second:", limiter.try_acquire("agent-1"))
    print("third blocked:", limiter.try_acquire("AGENT-1"))
    now[0] = 11.0
    print("after window:", limiter.try_acquire("agent-1"))


if __name__ == "__main__":
    main()
