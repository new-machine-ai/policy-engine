from __future__ import annotations

from runaway_cost import BudgetPolicy, BudgetTracker


def main() -> None:
    tracker = BudgetTracker(BudgetPolicy(max_tokens=100, max_tool_calls=2, max_cost_usd=0.10))
    tracker.record_tokens(90)
    tracker.record_tool_call()
    tracker.record_cost(0.08)

    print("status:", tracker.status().to_dict())
    print("projected:", tracker.would_exceed(tokens=20, tool_calls=1, cost_usd=0.03))


if __name__ == "__main__":
    main()
