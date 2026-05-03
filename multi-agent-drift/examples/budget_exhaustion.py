# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Context budget exhaustion emitting SIGWARN and SIGSTOP."""

from __future__ import annotations

from multi_agent_drift import AgentSignal, BudgetExceeded, ContextScheduler


def main() -> None:
    scheduler = ContextScheduler(total_budget=100, warn_threshold=0.75)
    for signal in AgentSignal:
        scheduler.on_signal(signal, lambda agent_id, emitted: print(f"signal={emitted.value} agent={agent_id}"))

    scheduler.allocate("researcher", "collect handoff evidence", max_tokens=100)
    scheduler.record_usage("researcher", lookup_tokens=70)
    scheduler.record_usage("researcher", lookup_tokens=10)
    try:
        scheduler.record_usage("researcher", reasoning_tokens=20)
    except BudgetExceeded as exc:
        print(f"blocked={exc}")

    print(scheduler.get_health_report())


if __name__ == "__main__":
    main()
