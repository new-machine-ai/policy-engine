# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Facade combining RBAC, reversibility, escalation, and kill-switch checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .escalation import EscalationDecision, EscalationHandler, EscalationRequest
from .kill_switch import KillSwitch
from .rbac import RBACManager, Role
from .reversibility import ReversibilityAssessment, ReversibilityChecker, ReversibilityLevel


@dataclass(frozen=True)
class HumanLoopDecision:
    """Decision returned by the human-loop guard."""

    allowed: bool
    decision: EscalationDecision
    reason: str
    agent_id: str
    session_id: str
    action: str
    role: Role
    reversibility: ReversibilityAssessment | None = None
    request: EscalationRequest | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "decision": self.decision.value,
            "reason": self.reason,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "action": self.action,
            "role": self.role.value,
            "reversibility": self.reversibility.to_dict() if self.reversibility else None,
            "request": self.request.to_dict() if self.request else None,
            "timestamp": self.timestamp.isoformat(),
        }


class HumanLoopGuard:
    """High-level evaluator for irreversible or sensitive agent actions."""

    def __init__(
        self,
        *,
        rbac: RBACManager | None = None,
        reversibility: ReversibilityChecker | None = None,
        escalation: EscalationHandler | None = None,
        kill_switch: KillSwitch | None = None,
        block_irreversible: bool = False,
    ) -> None:
        self.rbac = rbac or RBACManager()
        self.reversibility = reversibility or ReversibilityChecker(block_irreversible=block_irreversible)
        self.escalation = escalation or EscalationHandler()
        self.kill_switch = kill_switch or KillSwitch()

    def evaluate_action(
        self,
        agent_id: str,
        session_id: str,
        action: str,
        context: dict[str, Any] | None = None,
        in_flight_steps: list[dict[str, Any]] | None = None,
    ) -> HumanLoopDecision:
        context = context or {}
        role = self.rbac.get_role(agent_id)
        if self.kill_switch.is_stopped(agent_id):
            return HumanLoopDecision(
                allowed=False,
                decision=EscalationDecision.DENY,
                reason="agent is stopped by kill switch",
                agent_id=agent_id,
                session_id=session_id,
                action=action,
                role=role,
            )

        if not self.rbac.has_permission(agent_id, action):
            return HumanLoopDecision(
                allowed=False,
                decision=EscalationDecision.DENY,
                reason=f"role {role.value!r} lacks permission for action {action!r}",
                agent_id=agent_id,
                session_id=session_id,
                action=action,
                role=role,
            )

        assessment = self.reversibility.assess(action)
        if self.reversibility.should_block(action):
            return HumanLoopDecision(
                allowed=False,
                decision=EscalationDecision.DENY,
                reason="irreversible action blocked by policy",
                agent_id=agent_id,
                session_id=session_id,
                action=action,
                role=role,
                reversibility=assessment,
            )

        needs_approval = assessment.requires_extra_approval or assessment.level in {
            ReversibilityLevel.IRREVERSIBLE,
            ReversibilityLevel.UNKNOWN,
        }
        if needs_approval:
            request = self.escalation.escalate(
                agent_id=agent_id,
                action=action,
                reason=f"{assessment.level.value} action requires approval: {assessment.reason}",
                context_snapshot={
                    **context,
                    "session_id": session_id,
                    "in_flight_step_count": len(in_flight_steps or []),
                    "reversibility": assessment.level.value,
                },
            )
            return HumanLoopDecision(
                allowed=False,
                decision=request.decision,
                reason=request.reason,
                agent_id=agent_id,
                session_id=session_id,
                action=action,
                role=role,
                reversibility=assessment,
                request=request,
            )

        return HumanLoopDecision(
            allowed=True,
            decision=EscalationDecision.ALLOW,
            reason="action permitted",
            agent_id=agent_id,
            session_id=session_id,
            action=action,
            role=role,
            reversibility=assessment,
        )
