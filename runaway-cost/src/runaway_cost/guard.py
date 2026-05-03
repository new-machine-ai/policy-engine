# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Facade combining rate limits, budgets, and circuit breakers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .budget import BudgetPolicy, BudgetStatus, BudgetTracker
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
from .rate_limit import (
    AgentRateLimiter,
    ExecutionRing,
    RateLimitExceeded,
    RateLimitStats,
    SlidingWindowRateLimiter,
)


@dataclass(frozen=True)
class RunawayDecision:
    """Decision returned by the runaway-cost guard."""

    allowed: bool
    reason: str
    agent_id: str
    session_id: str
    operation: str
    retry_after: float = 0.0
    wait_seconds: float = 0.0
    budget_status: BudgetStatus | None = None
    rate_limit_status: RateLimitStats | None = None
    circuit_state: CircuitState = CircuitState.CLOSED
    metadata_hash: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "operation": self.operation,
            "retry_after": round(self.retry_after, 6),
            "wait_seconds": round(self.wait_seconds, 6),
            "budget_status": self.budget_status.to_dict() if self.budget_status else None,
            "rate_limit_status": self.rate_limit_status.to_dict() if self.rate_limit_status else None,
            "circuit_state": self.circuit_state.value,
            "metadata_hash": self.metadata_hash,
            "timestamp": self.timestamp.isoformat(),
        }


class RunawayCostGuard:
    """High-level guard for runaway retries and spending."""

    def __init__(
        self,
        *,
        budget_policy: BudgetPolicy | None = None,
        agent_rate_limiter: AgentRateLimiter | None = None,
        sliding_limiter: SlidingWindowRateLimiter | None = None,
        circuit_config: CircuitBreakerConfig | None = None,
    ) -> None:
        self.budget_policy = budget_policy or BudgetPolicy(
            max_tokens=100_000,
            max_tool_calls=1_000,
            max_cost_usd=100.0,
            max_duration_seconds=3600.0,
            max_retries=100,
        )
        self.agent_rate_limiter = agent_rate_limiter or AgentRateLimiter()
        self.sliding_limiter = sliding_limiter or SlidingWindowRateLimiter(max_calls_per_window=1000, window_size=60.0)
        self.circuit_config = circuit_config or CircuitBreakerConfig()
        self._budgets: dict[str, BudgetTracker] = {}
        self._circuits: dict[str, CircuitBreaker] = {}

    def evaluate_attempt(
        self,
        agent_id: str,
        session_id: str,
        operation: str,
        ring: ExecutionRing | str = ExecutionRing.RING_2_STANDARD,
        estimated_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        estimated_duration_seconds: float = 0.0,
    ) -> RunawayDecision:
        key = self._key(agent_id, session_id)
        budget = self._budget(key)
        circuit = self._circuit(agent_id)
        circuit_state = circuit.get_state()
        metadata_hash = _metadata_hash(
            {
                "agent_id": agent_id,
                "session_id": session_id,
                "operation": operation,
                "ring": str(ring),
            }
        )
        if circuit_state is CircuitState.OPEN:
            return RunawayDecision(
                allowed=False,
                reason="circuit open",
                agent_id=agent_id,
                session_id=session_id,
                operation=operation,
                retry_after=circuit.retry_after(),
                budget_status=budget.status(),
                circuit_state=circuit_state,
                metadata_hash=metadata_hash,
            )

        try:
            self.agent_rate_limiter.check(agent_id, session_id, ring)
        except RateLimitExceeded as exc:
            return RunawayDecision(
                allowed=False,
                reason=str(exc),
                agent_id=agent_id,
                session_id=session_id,
                operation=operation,
                wait_seconds=exc.wait_seconds,
                budget_status=budget.status(),
                rate_limit_status=self.agent_rate_limiter.get_stats(agent_id, session_id),
                circuit_state=circuit_state,
                metadata_hash=metadata_hash,
            )

        if not self.sliding_limiter.try_acquire(agent_id):
            return RunawayDecision(
                allowed=False,
                reason="sliding-window rate limit exceeded",
                agent_id=agent_id,
                session_id=session_id,
                operation=operation,
                budget_status=budget.status(),
                rate_limit_status=self.agent_rate_limiter.get_stats(agent_id, session_id),
                circuit_state=circuit_state,
                metadata_hash=metadata_hash,
            )

        projected_reasons = budget.would_exceed(
            tokens=estimated_tokens,
            tool_calls=1,
            cost_usd=estimated_cost_usd,
            duration_seconds=estimated_duration_seconds,
        )
        if projected_reasons:
            return RunawayDecision(
                allowed=False,
                reason="budget would be exceeded: " + "; ".join(projected_reasons),
                agent_id=agent_id,
                session_id=session_id,
                operation=operation,
                budget_status=budget.status(),
                rate_limit_status=self.agent_rate_limiter.get_stats(agent_id, session_id),
                circuit_state=circuit_state,
                metadata_hash=metadata_hash,
            )

        return RunawayDecision(
            allowed=True,
            reason="allowed",
            agent_id=agent_id,
            session_id=session_id,
            operation=operation,
            budget_status=budget.status(),
            rate_limit_status=self.agent_rate_limiter.get_stats(agent_id, session_id),
            circuit_state=circuit_state,
            metadata_hash=metadata_hash,
        )

    def record_success(
        self,
        agent_id: str,
        session_id: str,
        *,
        tokens: int = 0,
        tool_calls: int = 1,
        cost_usd: float = 0.0,
        duration_seconds: float = 0.0,
    ) -> BudgetStatus:
        budget = self._budget(self._key(agent_id, session_id))
        budget.record_tokens(tokens)
        budget.record_tool_call(tool_calls)
        budget.record_cost(cost_usd)
        budget.record_duration(duration_seconds)
        self._circuit(agent_id).record_success()
        return budget.status()

    def record_failure(
        self,
        agent_id: str,
        session_id: str,
        *,
        retries: int = 1,
        tokens: int = 0,
        cost_usd: float = 0.0,
        duration_seconds: float = 0.0,
    ) -> BudgetStatus:
        budget = self._budget(self._key(agent_id, session_id))
        budget.record_retry(retries)
        budget.record_tokens(tokens)
        budget.record_cost(cost_usd)
        budget.record_duration(duration_seconds)
        self._circuit(agent_id).record_failure()
        return budget.status()

    def report(self) -> dict[str, Any]:
        return {
            "budgets": {
                key: tracker.status().to_dict()
                for key, tracker in sorted(self._budgets.items())
            },
            "circuits": {
                agent_id: {
                    "state": circuit.get_state().value,
                    "failure_count": circuit.failure_count,
                    "success_count": circuit.success_count,
                    "retry_after": round(circuit.retry_after(), 6),
                }
                for agent_id, circuit in sorted(self._circuits.items())
            },
        }

    def _budget(self, key: str) -> BudgetTracker:
        return self._budgets.setdefault(key, BudgetTracker(self.budget_policy))

    def _circuit(self, agent_id: str) -> CircuitBreaker:
        return self._circuits.setdefault(agent_id, CircuitBreaker(agent_id, self.circuit_config))

    @staticmethod
    def _key(agent_id: str, session_id: str) -> str:
        return f"{agent_id}:{session_id}"


def _metadata_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
