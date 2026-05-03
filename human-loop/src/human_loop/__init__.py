# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Human approval, role gates, kill switches, and reversibility checks."""

from __future__ import annotations

from .escalation import (
    ApprovalBackend,
    DefaultTimeoutAction,
    EscalationDecision,
    EscalationHandler,
    EscalationPolicy,
    EscalationRequest,
    EscalationResult,
    InMemoryApprovalQueue,
    QuorumConfig,
    WebhookApprovalBackend,
)
from .guard import HumanLoopDecision, HumanLoopGuard
from .kill_switch import HandoffStatus, KillReason, KillResult, KillSignal, KillSwitch, StepHandoff
from .rbac import RBACManager, Role, RolePolicy
from .reversibility import (
    ActionDescriptor,
    CompensatingAction,
    ReversibilityAssessment,
    ReversibilityChecker,
    ReversibilityEntry,
    ReversibilityLevel,
    ReversibilityRegistry,
)

__all__ = [
    "ActionDescriptor",
    "ApprovalBackend",
    "CompensatingAction",
    "DefaultTimeoutAction",
    "EscalationDecision",
    "EscalationHandler",
    "EscalationPolicy",
    "EscalationRequest",
    "EscalationResult",
    "HandoffStatus",
    "HumanLoopDecision",
    "HumanLoopGuard",
    "InMemoryApprovalQueue",
    "KillReason",
    "KillResult",
    "KillSignal",
    "KillSwitch",
    "QuorumConfig",
    "RBACManager",
    "ReversibilityAssessment",
    "ReversibilityChecker",
    "ReversibilityEntry",
    "ReversibilityLevel",
    "ReversibilityRegistry",
    "Role",
    "RolePolicy",
    "StepHandoff",
    "WebhookApprovalBackend",
]
