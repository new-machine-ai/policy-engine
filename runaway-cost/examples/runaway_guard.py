from __future__ import annotations

from runaway_cost import BudgetPolicy, RunawayCostGuard


def main() -> None:
    guard = RunawayCostGuard(
        budget_policy=BudgetPolicy(max_tokens=300, max_tool_calls=3, max_cost_usd=0.05)
    )

    first = guard.evaluate_attempt(
        "agent-1",
        "session-1",
        "call_model",
        estimated_tokens=200,
        estimated_cost_usd=0.02,
    )
    print("first:", first.to_dict())
    guard.record_success("agent-1", "session-1", tokens=200, cost_usd=0.02)

    retry = guard.evaluate_attempt(
        "agent-1",
        "session-1",
        "call_model",
        estimated_tokens=200,
        estimated_cost_usd=0.04,
    )
    print("costly retry:", retry.to_dict())


if __name__ == "__main__":
    main()
