# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""SIGSTOP/SIGKILL kill-switch controls with handoff support."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class KillReason(str, Enum):
    """Why an agent was stopped or killed."""

    BEHAVIORAL_DRIFT = "behavioral_drift"
    RATE_LIMIT = "rate_limit"
    RING_BREACH = "ring_breach"
    MANUAL = "manual"
    QUARANTINE_TIMEOUT = "quarantine_timeout"
    SESSION_TIMEOUT = "session_timeout"


class KillSignal(str, Enum):
    """Kill-switch signal."""

    SIGSTOP = "sigstop"
    SIGKILL = "sigkill"


class HandoffStatus(str, Enum):
    """Status of an in-flight step after a kill."""

    PENDING = "pending"
    HANDED_OFF = "handed_off"
    FAILED = "failed"
    COMPENSATED = "compensated"


@dataclass(frozen=True)
class StepHandoff:
    """In-flight step handoff or compensation marker."""

    step_id: str
    saga_id: str
    from_agent: str
    to_agent: str | None = None
    status: HandoffStatus = HandoffStatus.COMPENSATED

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "saga_id": self.saga_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "status": self.status.value,
        }


@dataclass(frozen=True)
class KillResult:
    """Result of a kill-switch operation."""

    kill_id: str = field(default_factory=lambda: f"kill:{uuid.uuid4().hex[:8]}")
    agent_did: str = ""
    session_id: str = ""
    signal: KillSignal = KillSignal.SIGKILL
    reason: KillReason = KillReason.MANUAL
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    handoffs: tuple[StepHandoff, ...] = ()
    handoff_success_count: int = 0
    compensation_triggered: bool = False
    terminated: bool = False
    stopped: bool = False
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kill_id": self.kill_id,
            "agent_did": self.agent_did,
            "session_id": self.session_id,
            "signal": self.signal.value,
            "reason": self.reason.value,
            "timestamp": self.timestamp.isoformat(),
            "handoffs": [handoff.to_dict() for handoff in self.handoffs],
            "handoff_success_count": self.handoff_success_count,
            "compensation_triggered": self.compensation_triggered,
            "terminated": self.terminated,
            "stopped": self.stopped,
            "details": self.details,
        }


class KillSwitch:
    """Kill switch with process callbacks, stop-state, and handoff support."""

    def __init__(self) -> None:
        self._kill_history: list[KillResult] = []
        self._substitutes: dict[str, list[str]] = {}
        self._agents: dict[str, Callable[[], None]] = {}
        self._stopped: set[str] = set()

    def register_agent(self, agent_did: str, process_handle: Callable[[], None]) -> None:
        self._agents[agent_did] = process_handle

    def unregister_agent(self, agent_did: str) -> None:
        self._agents.pop(agent_did, None)

    def register_substitute(self, session_id: str, agent_did: str) -> None:
        self._substitutes.setdefault(session_id, []).append(agent_did)

    def unregister_substitute(self, session_id: str, agent_did: str) -> None:
        substitutes = self._substitutes.get(session_id, [])
        if agent_did in substitutes:
            substitutes.remove(agent_did)

    def is_stopped(self, agent_did: str) -> bool:
        return agent_did in self._stopped

    def resume_agent(self, agent_did: str) -> bool:
        if agent_did not in self._stopped:
            return False
        self._stopped.remove(agent_did)
        return True

    def kill(
        self,
        agent_did: str,
        session_id: str,
        reason: KillReason,
        *,
        signal: KillSignal = KillSignal.SIGKILL,
        in_flight_steps: list[dict[str, Any]] | None = None,
        details: str = "",
    ) -> KillResult:
        if signal == KillSignal.SIGSTOP:
            self._stopped.add(agent_did)
            result = KillResult(
                agent_did=agent_did,
                session_id=session_id,
                signal=signal,
                reason=reason,
                stopped=True,
                details=details,
            )
            self._kill_history.append(result)
            return result

        substitute = self._find_substitute(session_id, agent_did)
        handoffs = tuple(self._handoff_steps(agent_did, substitute, in_flight_steps or []))
        callback = self._agents.get(agent_did)
        terminated = False
        if callback is not None:
            callback()
            terminated = True
        result = KillResult(
            agent_did=agent_did,
            session_id=session_id,
            signal=signal,
            reason=reason,
            handoffs=handoffs,
            handoff_success_count=sum(1 for handoff in handoffs if handoff.status == HandoffStatus.HANDED_OFF),
            compensation_triggered=any(handoff.status == HandoffStatus.COMPENSATED for handoff in handoffs),
            terminated=terminated,
            details=details,
        )
        self._kill_history.append(result)
        self._stopped.discard(agent_did)
        self.unregister_substitute(session_id, agent_did)
        self.unregister_agent(agent_did)
        return result

    def _handoff_steps(
        self,
        agent_did: str,
        substitute: str | None,
        in_flight_steps: list[dict[str, Any]],
    ) -> list[StepHandoff]:
        handoffs: list[StepHandoff] = []
        for step in in_flight_steps:
            if substitute is not None:
                handoffs.append(
                    StepHandoff(
                        step_id=str(step.get("step_id", "")),
                        saga_id=str(step.get("saga_id", "")),
                        from_agent=agent_did,
                        to_agent=substitute,
                        status=HandoffStatus.HANDED_OFF,
                    )
                )
            else:
                handoffs.append(
                    StepHandoff(
                        step_id=str(step.get("step_id", "")),
                        saga_id=str(step.get("saga_id", "")),
                        from_agent=agent_did,
                        status=HandoffStatus.COMPENSATED,
                    )
                )
        return handoffs

    def _find_substitute(self, session_id: str, exclude_did: str) -> str | None:
        for substitute in self._substitutes.get(session_id, []):
            if substitute != exclude_did:
                return substitute
        return None

    @property
    def kill_history(self) -> list[KillResult]:
        return list(self._kill_history)

    @property
    def total_kills(self) -> int:
        return len(self._kill_history)

    @property
    def total_handoffs(self) -> int:
        return sum(result.handoff_success_count for result in self._kill_history)
