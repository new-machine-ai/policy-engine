# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Handoff conflicts using intent locks and vector clocks."""

from __future__ import annotations

from multi_agent_drift import (
    CausalViolationError,
    IntentLockManager,
    LockContentionError,
    LockIntent,
    VectorClockManager,
)


def main() -> None:
    locks = IntentLockManager()
    read_lock = locks.acquire("agent-a", "session-1", "/customer/123", LockIntent.READ)
    print(f"read_lock={read_lock.lock_id}")
    try:
        locks.acquire("agent-b", "session-1", "/customer/123", LockIntent.WRITE)
    except LockContentionError as exc:
        print(f"write_blocked={exc}")
    locks.release(read_lock.lock_id)
    write_lock = locks.acquire("agent-b", "session-1", "/customer/123", LockIntent.WRITE)
    print(f"write_lock={write_lock.lock_id}")

    clocks = VectorClockManager()
    clocks.write("/customer/123", "agent-a")
    try:
        clocks.write("/customer/123", "agent-b")
    except CausalViolationError as exc:
        print(f"causal_blocked={exc}")
    clocks.read("/customer/123", "agent-b")
    clock = clocks.write("/customer/123", "agent-b")
    print(f"merged_clock={clock.clocks}")


if __name__ == "__main__":
    main()
