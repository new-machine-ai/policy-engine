# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Human approval escalation primitives."""

from __future__ import annotations

import json
import re
import threading
import urllib.request
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Callable

from .privacy import payload_hash, summarize_context


class EscalationDecision(str, Enum):
    """Possible escalation outcomes."""

    ALLOW = "allow"
    DENY = "deny"
    ESCALATE = "escalate"
    PENDING = "pending"
    TIMEOUT = "timeout"


class DefaultTimeoutAction(str, Enum):
    """Default action when a human does not respond."""

    DENY = "deny"
    ALLOW = "allow"


@dataclass(frozen=True)
class QuorumConfig:
    """M-of-N approval quorum."""

    required_approvals: int = 2
    total_approvers: int = 3
    required_denials: int = 1

    def __post_init__(self) -> None:
        if self.required_approvals < 1:
            raise ValueError("required_approvals must be >= 1")
        if self.total_approvers < self.required_approvals:
            raise ValueError("total_approvers must be >= required_approvals")
        if self.required_denials < 1:
            raise ValueError("required_denials must be >= 1")


@dataclass
class EscalationRequest:
    """A request for human approval of an action."""

    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    agent_id: str = ""
    action: str = ""
    reason: str = ""
    context_hash: str = ""
    context_summary: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    resolved_at: datetime | None = None
    decision: EscalationDecision = EscalationDecision.PENDING
    resolved_by: str | None = None
    votes: list[tuple[str, str, datetime]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "agent_id": self.agent_id,
            "action": self.action,
            "reason": self.reason,
            "context_hash": self.context_hash,
            "context_summary": dict(self.context_summary),
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "decision": self.decision.value,
            "resolved_by": self.resolved_by,
            "votes": [
                {"approver": approver, "decision": decision, "timestamp": timestamp.isoformat()}
                for approver, decision, timestamp in self.votes
            ],
        }


@dataclass(frozen=True)
class EscalationResult:
    """Result of an escalation policy evaluation."""

    action: str
    decision: EscalationDecision
    reason: str | None
    request: EscalationRequest | None = None
    policy_name: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "decision": self.decision.value,
            "reason": self.reason,
            "request": self.request.to_dict() if self.request else None,
            "policy_name": self.policy_name,
            "timestamp": self.timestamp.isoformat(),
        }


class ApprovalBackend(ABC):
    """Abstract interface for human approval backends."""

    @abstractmethod
    def submit(self, request: EscalationRequest) -> None: ...

    @abstractmethod
    def get_decision(self, request_id: str) -> EscalationRequest | None: ...

    @abstractmethod
    def approve(self, request_id: str, approver: str = "") -> bool: ...

    @abstractmethod
    def deny(self, request_id: str, approver: str = "") -> bool: ...

    @abstractmethod
    def list_pending(self) -> list[EscalationRequest]: ...


class InMemoryApprovalQueue(ApprovalBackend):
    """Thread-safe in-memory approval queue."""

    def __init__(self) -> None:
        self._requests: dict[str, EscalationRequest] = {}
        self._events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def submit(self, request: EscalationRequest) -> None:
        with self._lock:
            self._requests[request.request_id] = request
            self._events[request.request_id] = threading.Event()

    def get_decision(self, request_id: str) -> EscalationRequest | None:
        with self._lock:
            return self._requests.get(request_id)

    def approve(self, request_id: str, approver: str = "") -> bool:
        return self._vote(request_id, approver or "human", EscalationDecision.ALLOW)

    def deny(self, request_id: str, approver: str = "") -> bool:
        return self._vote(request_id, approver or "human", EscalationDecision.DENY)

    def list_pending(self) -> list[EscalationRequest]:
        with self._lock:
            return [
                request
                for request in self._requests.values()
                if request.decision == EscalationDecision.PENDING
            ]

    def wait_for_decision(self, request_id: str, timeout: float | None = None) -> EscalationRequest | None:
        with self._lock:
            event = self._events.get(request_id)
        if event is None:
            return None
        event.wait(timeout=timeout)
        return self.get_decision(request_id)

    def _vote(self, request_id: str, approver: str, decision: EscalationDecision) -> bool:
        with self._lock:
            request = self._requests.get(request_id)
            if request is None or request.decision not in {EscalationDecision.PENDING, decision}:
                return False
            if any(existing_approver == approver for existing_approver, _, _ in request.votes):
                return False
            request.votes.append((approver, decision.value, datetime.now(UTC)))
            event = self._events.get(request_id)
        if event:
            event.set()
        return True


class WebhookApprovalBackend(ApprovalBackend):
    """Approval backend that stores state locally and POSTs new requests to a webhook."""

    def __init__(self, webhook_url: str, headers: dict[str, str] | None = None) -> None:
        self._inner = InMemoryApprovalQueue()
        self._webhook_url = webhook_url
        self._headers = headers or {}

    def submit(self, request: EscalationRequest) -> None:
        self._inner.submit(request)
        self._notify(request)

    def get_decision(self, request_id: str) -> EscalationRequest | None:
        return self._inner.get_decision(request_id)

    def approve(self, request_id: str, approver: str = "") -> bool:
        return self._inner.approve(request_id, approver)

    def deny(self, request_id: str, approver: str = "") -> bool:
        return self._inner.deny(request_id, approver)

    def list_pending(self) -> list[EscalationRequest]:
        return self._inner.list_pending()

    def wait_for_decision(self, request_id: str, timeout: float | None = None) -> EscalationRequest | None:
        return self._inner.wait_for_decision(request_id, timeout)

    def _notify(self, request: EscalationRequest) -> None:
        payload = json.dumps(request.to_dict(), sort_keys=True).encode("utf-8")
        req = urllib.request.Request(
            self._webhook_url,
            data=payload,
            headers={**self._headers, "Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)


class EscalationHandler:
    """Creates, resolves, and audits human approval requests."""

    def __init__(
        self,
        backend: ApprovalBackend | None = None,
        timeout_seconds: float = 300,
        default_action: DefaultTimeoutAction = DefaultTimeoutAction.DENY,
        on_escalate: Callable[[EscalationRequest], None] | None = None,
        quorum: QuorumConfig | None = None,
        fatigue_window_seconds: float = 60.0,
        fatigue_threshold: int | None = None,
    ) -> None:
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")
        if fatigue_window_seconds <= 0:
            raise ValueError("fatigue_window_seconds must be positive")
        if fatigue_threshold is not None and fatigue_threshold < 1:
            raise ValueError("fatigue_threshold must be >= 1 when provided")
        self.backend = backend or InMemoryApprovalQueue()
        self.timeout_seconds = timeout_seconds
        self.default_action = default_action
        self.quorum = quorum
        self._on_escalate = on_escalate
        self._fatigue_window = fatigue_window_seconds
        self._fatigue_threshold = fatigue_threshold
        self._escalation_times: dict[str, list[datetime]] = {}
        self._audit: list[dict[str, Any]] = []

    def escalate(
        self,
        agent_id: str,
        action: str,
        reason: str,
        context_snapshot: dict[str, Any] | None = None,
    ) -> EscalationRequest:
        if self._check_fatigue(agent_id):
            request = EscalationRequest(
                agent_id=agent_id,
                action=action,
                reason=f"Auto-denied: escalation fatigue ({reason})",
                context_hash=payload_hash(context_snapshot or {}),
                context_summary=summarize_context(context_snapshot or {}),
                expires_at=datetime.now(UTC),
                resolved_at=datetime.now(UTC),
                decision=EscalationDecision.DENY,
                resolved_by="system:fatigue_detector",
            )
            self._record("fatigue_denied", request)
            return request

        now = datetime.now(UTC)
        self._escalation_times.setdefault(agent_id, []).append(now)
        request = EscalationRequest(
            agent_id=agent_id,
            action=action,
            reason=reason,
            context_hash=payload_hash(context_snapshot or {}),
            context_summary=summarize_context(context_snapshot or {}),
            expires_at=now + timedelta(seconds=self.timeout_seconds),
        )
        self.backend.submit(request)
        if self._on_escalate:
            self._on_escalate(request)
        self._record("escalated", request)
        return request

    def approve(self, request_id: str, approver: str = "human") -> bool:
        accepted = self.backend.approve(request_id, approver)
        request = self.backend.get_decision(request_id)
        if accepted and request:
            self._record("approved_vote", request)
        return accepted

    def deny(self, request_id: str, approver: str = "human") -> bool:
        accepted = self.backend.deny(request_id, approver)
        request = self.backend.get_decision(request_id)
        if accepted and request:
            self._record("denied_vote", request)
        return accepted

    def resolve(self, request_id: str) -> EscalationDecision:
        request = self._wait_for_request(request_id)
        if request is None:
            return EscalationDecision.DENY
        decision = self._resolve_votes_or_timeout(request)
        self._record("resolved", request)
        return decision

    @property
    def audit_trail(self) -> list[dict[str, Any]]:
        return list(self._audit)

    def _wait_for_request(self, request_id: str) -> EscalationRequest | None:
        wait = getattr(self.backend, "wait_for_decision", None)
        if callable(wait):
            return wait(request_id, self.timeout_seconds)
        return self.backend.get_decision(request_id)

    def _resolve_votes_or_timeout(self, request: EscalationRequest) -> EscalationDecision:
        approvals = len({approver for approver, vote, _ in request.votes if vote == EscalationDecision.ALLOW.value})
        denials = len({approver for approver, vote, _ in request.votes if vote == EscalationDecision.DENY.value})

        if self.quorum:
            if denials >= self.quorum.required_denials:
                return self._finalize(request, EscalationDecision.DENY, "quorum")
            if approvals >= self.quorum.required_approvals:
                return self._finalize(request, EscalationDecision.ALLOW, "quorum")
        else:
            if denials:
                return self._finalize(request, EscalationDecision.DENY, "human")
            if approvals:
                return self._finalize(request, EscalationDecision.ALLOW, "human")

        timeout_decision = (
            EscalationDecision.ALLOW
            if self.default_action == DefaultTimeoutAction.ALLOW
            else EscalationDecision.DENY
        )
        return self._finalize(request, timeout_decision, "timeout", timed_out=True)

    @staticmethod
    def _finalize(
        request: EscalationRequest,
        decision: EscalationDecision,
        resolved_by: str,
        *,
        timed_out: bool = False,
    ) -> EscalationDecision:
        request.decision = EscalationDecision.TIMEOUT if timed_out else decision
        request.resolved_at = datetime.now(UTC)
        request.resolved_by = resolved_by
        return decision

    def _check_fatigue(self, agent_id: str) -> bool:
        if self._fatigue_threshold is None:
            return False
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=self._fatigue_window)
        recent = [timestamp for timestamp in self._escalation_times.get(agent_id, []) if timestamp > cutoff]
        self._escalation_times[agent_id] = recent
        return len(recent) >= self._fatigue_threshold

    def _record(self, event_type: str, request: EscalationRequest) -> None:
        self._audit.append(
            {
                "event_type": event_type,
                "request_id": request.request_id,
                "agent_id": request.agent_id,
                "action": request.action,
                "reason": request.reason,
                "decision": request.decision.value,
                "context_hash": request.context_hash,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )


@dataclass
class EscalationPolicy:
    """Rules for deciding whether an action must be escalated."""

    actions_requiring_approval: list[str] = field(default_factory=list)
    action_patterns_requiring_approval: list[str] = field(default_factory=list)
    classifications_requiring_approval: list[str] = field(default_factory=list)
    handler: EscalationHandler = field(default_factory=EscalationHandler)
    policy_name: str = "default"

    def requires_approval(self, action: str, context: dict[str, Any] | None = None) -> bool:
        context = context or {}
        if action in self.actions_requiring_approval:
            return True
        if any(re.search(pattern, action) for pattern in self.action_patterns_requiring_approval):
            return True
        return str(context.get("classification", "")) in self.classifications_requiring_approval

    def evaluate(
        self,
        agent_id: str,
        action: str,
        context: dict[str, Any] | None = None,
        reason: str = "human approval required",
    ) -> EscalationResult:
        if not self.requires_approval(action, context):
            return EscalationResult(
                action=action,
                decision=EscalationDecision.ALLOW,
                reason=None,
                policy_name=self.policy_name,
            )
        request = self.handler.escalate(agent_id, action, reason, context)
        return EscalationResult(
            action=action,
            decision=request.decision if request.decision != EscalationDecision.PENDING else EscalationDecision.PENDING,
            reason=reason,
            request=request,
            policy_name=self.policy_name,
        )
