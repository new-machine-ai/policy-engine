"""Google ADK callback governance quickstart.

This deterministic demo mirrors the Agent-OS Google ADK sample but routes all
decisions through policy-engine's local GoogleADKKernel. It does not create a
live model or require Google credentials.
"""

from _shared import step
from policy_engine.adapters.google_adk import GoogleADKKernel


def _print_block(result: dict | None) -> None:
    if result and result.get("error"):
        print(f"    BLOCKED - {result['error']}")


def main() -> None:
    framework = "google_adk_callbacks"
    kernel = GoogleADKKernel(
        max_tool_calls=10,
        allowed_tools=["search", "summarize"],
        blocked_tools=["exec_code", "shell"],
        blocked_patterns=["DROP TABLE", "rm -rf"],
        max_budget=5.0,
        on_violation=lambda _e: None,
    )

    print("=" * 60)
    print("  Google ADK Agent - Governance Quickstart")
    print("=" * 60)

    step(framework, "Blocking an explicitly denied tool.")
    result = kernel.before_tool_callback(
        tool_name="shell",
        tool_args={},
        agent_name="adk-agent",
    )
    _print_block(result)

    step(framework, "Blocking a tool that is outside the allowlist.")
    result = kernel.before_tool_callback(
        tool_name="web_scraper",
        tool_args={},
        agent_name="adk-agent",
    )
    _print_block(result)

    step(framework, "Blocking dangerous content in tool arguments.")
    result = kernel.before_tool_callback(
        tool_name="search",
        tool_args={"query": "DROP TABLE sessions; SELECT 1"},
        agent_name="adk-agent",
    )
    _print_block(result)

    step(framework, "Allowing a compliant tool call.")
    result = kernel.before_tool_callback(
        tool_name="search",
        tool_args={"query": "AI governance best practices"},
        agent_name="adk-agent",
    )
    if result is None:
        print("    ALLOWED - all policy gates passed")

    stats = kernel.get_stats()
    print("\n-- Kernel Stats ----------------------------------------")
    print(f"  violations={stats['violations']}  audit_events={stats['audit_events']}")
    print(f"  budget_spent={stats['budget_spent']}  budget_limit={stats['budget_limit']}")

    print("\n-- Audit Trail -----------------------------------------")
    for i, violation in enumerate(kernel.get_violations(), 1):
        print(
            f"  [{i}] BLOCKED  policy={violation.policy_name!r}  "
            f"reason={violation.description!r}"
        )
    for j, entry in enumerate(
        kernel.get_audit_log()[-1:],
        len(kernel.get_violations()) + 1,
    ):
        print(
            f"  [{j}] ALLOWED  tool={entry.details.get('tool')!r}  "
            f"agent={entry.agent_name!r}"
        )

    print("\nGoogle ADK governance demo complete.")


if __name__ == "__main__":
    main()
