# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Facade combining multi-agent drift primitives."""

from __future__ import annotations

from typing import Any

from .context_budget import ContextScheduler
from .conversation import ConversationAlert, ConversationGuardian
from .drift import DriftDetector, DriftReport
from .saga import FanOutOrchestrator, SagaOrchestrator
from .session import IntentLockManager, LockIntent, VectorClock, VectorClockManager


class MultiAgentDriftMonitor:
    """Small orchestrating facade for context, drift, handoffs, and sagas."""

    def __init__(
        self,
        *,
        context_scheduler: ContextScheduler | None = None,
        conversation_guardian: ConversationGuardian | None = None,
        drift_detector: DriftDetector | None = None,
        lock_manager: IntentLockManager | None = None,
        vector_clocks: VectorClockManager | None = None,
        saga_orchestrator: SagaOrchestrator | None = None,
        fan_out: FanOutOrchestrator | None = None,
    ) -> None:
        self.context_scheduler = context_scheduler or ContextScheduler()
        self.conversation_guardian = conversation_guardian or ConversationGuardian()
        self.drift_detector = drift_detector or DriftDetector()
        self.lock_manager = lock_manager or IntentLockManager()
        self.vector_clocks = vector_clocks or VectorClockManager()
        self.saga_orchestrator = saga_orchestrator or SagaOrchestrator()
        self.fan_out = fan_out or FanOutOrchestrator()

    def analyze_message(
        self,
        conversation_id: str,
        sender: str,
        receiver: str,
        content: str,
    ) -> ConversationAlert:
        return self.conversation_guardian.analyze_message(conversation_id, sender, receiver, content)

    def scan_drift(self, sources: list[dict[str, Any]]) -> DriftReport:
        return self.drift_detector.scan(sources)

    def acquire_handoff_lock(
        self,
        agent_did: str,
        session_id: str,
        resource_path: str,
        intent: LockIntent,
    ):
        return self.lock_manager.acquire(agent_did, session_id, resource_path, intent)

    def record_handoff_read(self, path: str, agent_did: str) -> VectorClock:
        return self.vector_clocks.read(path, agent_did)

    def record_handoff_write(self, path: str, agent_did: str, *, strict: bool = True) -> VectorClock:
        return self.vector_clocks.write(path, agent_did, strict=strict)

    def health_report(self) -> dict[str, Any]:
        return {
            "context": self.context_scheduler.get_health_report(),
            "conversation_alerts": len(self.conversation_guardian.alerts),
            "active_locks": self.lock_manager.active_lock_count,
            "tracked_paths": self.vector_clocks.tracked_paths,
            "active_sagas": len(self.saga_orchestrator.active_sagas),
            "active_fanouts": len(self.fan_out.active_groups),
        }

