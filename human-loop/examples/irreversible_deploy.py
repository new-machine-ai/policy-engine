# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Irreversible deploy requiring human approval."""

from __future__ import annotations

from human_loop import HumanLoopGuard, Role


def main() -> None:
    guard = HumanLoopGuard()
    guard.rbac.assign_role("agent-1", Role.ADMIN)
    decision = guard.evaluate_action("agent-1", "session-1", "deploy", {"target": "production"})
    print(decision.to_dict())


if __name__ == "__main__":
    main()
