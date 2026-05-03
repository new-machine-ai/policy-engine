# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Reversibility registry example."""

from __future__ import annotations

from human_loop import ActionDescriptor, ReversibilityLevel, ReversibilityRegistry


def main() -> None:
    registry = ReversibilityRegistry("session-1")
    registry.register(
        ActionDescriptor(
            action_id="deploy-prod",
            execute_api="deploy",
            undo_api="rollback",
            reversibility=ReversibilityLevel.IRREVERSIBLE,
            undo_window_seconds=600,
            compensation_method="rollback_deploy",
        )
    )
    registry.mark_undo_unhealthy("deploy-prod")
    print([entry.to_dict() for entry in registry.entries])
    print({"non_reversible_actions": registry.non_reversible_actions})


if __name__ == "__main__":
    main()
