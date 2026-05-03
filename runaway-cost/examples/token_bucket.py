from __future__ import annotations

from runaway_cost import RateLimitConfig, TokenBucket


def main() -> None:
    now = [0.0]
    bucket = TokenBucket.from_config(
        RateLimitConfig(capacity=2, refill_rate=1, initial_tokens=1),
        clock=lambda: now[0],
    )

    print("consume #1:", bucket.consume())
    print("consume #2:", bucket.consume())
    print("wait:", bucket.time_until_available())
    now[0] += 1.0
    print("consume after refill:", bucket.consume())


if __name__ == "__main__":
    main()
