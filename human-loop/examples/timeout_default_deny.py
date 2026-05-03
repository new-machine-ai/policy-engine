# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Timeout default-deny example."""

from __future__ import annotations

from human_loop import DefaultTimeoutAction, EscalationHandler


def main() -> None:
    handler = EscalationHandler(timeout_seconds=0, default_action=DefaultTimeoutAction.DENY)
    request = handler.escalate("agent-1", "execute_trade", "settled trade")
    decision = handler.resolve(request.request_id)
    print({"request_id": request.request_id, "decision": decision.value})


if __name__ == "__main__":
    main()
