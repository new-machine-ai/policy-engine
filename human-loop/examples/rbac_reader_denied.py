# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""RBAC denying reader actions."""

from __future__ import annotations

from human_loop import HumanLoopGuard


def main() -> None:
    guard = HumanLoopGuard()
    print(guard.evaluate_action("reader-agent", "session-1", "delete_file").to_dict())
    print(guard.evaluate_action("reader-agent", "session-1", "write_file").to_dict())


if __name__ == "__main__":
    main()
