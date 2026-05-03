# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Quorum approval example."""

from __future__ import annotations

from human_loop import EscalationDecision, EscalationHandler, QuorumConfig


def main() -> None:
    handler = EscalationHandler(timeout_seconds=0, quorum=QuorumConfig(required_approvals=2, total_approvers=3))
    request = handler.escalate("agent-1", "deploy", "production deploy")
    handler.approve(request.request_id, "alice")
    handler.approve(request.request_id, "bob")
    decision = handler.resolve(request.request_id)
    assert decision == EscalationDecision.ALLOW
    print({"request_id": request.request_id, "decision": decision.value})


if __name__ == "__main__":
    main()
