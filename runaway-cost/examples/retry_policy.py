from __future__ import annotations

from runaway_cost import RetryExhausted, retry


def main() -> None:
    attempts = {"count": 0}

    @retry(max_attempts=3, backoff_base=0.0)
    def flaky() -> str:
        attempts["count"] += 1
        raise RuntimeError("temporary upstream failure")

    try:
        flaky()
    except RetryExhausted as exc:
        print("exhausted:", exc.state.to_dict())


if __name__ == "__main__":
    main()
