# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Context budget scheduler for multi-agent sessions."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Callable


class AgentSignal(str, Enum):
    """Scheduler signals for context budget enforcement."""

    SIGSTOP = "sigstop"
    SIGWARN = "sigwarn"
    SIGRESUME = "sigresume"


@dataclass(frozen=True)
class ContextWindow:
    """An allocated context window for an agent task."""

    agent_id: str
    task: str
    lookup_budget: int
    reasoning_budget: int
    total: int
    created_at: float = field(default_factory=time.time)

    @property
    def lookup_ratio(self) -> float:
        return self.lookup_budget / self.total if self.total else 0.0

    @property
    def reasoning_ratio(self) -> float:
        return self.reasoning_budget / self.total if self.total else 0.0


class ContextPriority(IntEnum):
    """Task priority levels for context allocation."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class UsageRecord:
    """Tracks actual token usage by an agent."""

    agent_id: str
    window: ContextWindow
    lookup_used: int = 0
    reasoning_used: int = 0
    started_at: float = field(default_factory=time.time)
    stopped: bool = False
    stop_reason: str | None = None

    @property
    def total_used(self) -> int:
        return self.lookup_used + self.reasoning_used

    @property
    def remaining(self) -> int:
        return max(0, self.window.total - self.total_used)

    @property
    def utilization(self) -> float:
        return self.total_used / self.window.total if self.window.total else 0.0


class BudgetExceeded(Exception):
    """Raised when an agent exceeds its context budget."""

    def __init__(self, agent_id: str, budget: int, used: int) -> None:
        self.agent_id = agent_id
        self.budget = budget
        self.used = used
        super().__init__(f"Agent {agent_id} exceeded context budget: {used}/{budget} tokens")


_MIN_CONTEXT: dict[ContextPriority, int] = {
    ContextPriority.CRITICAL: 4000,
    ContextPriority.HIGH: 2000,
    ContextPriority.NORMAL: 1000,
    ContextPriority.LOW: 500,
}


class ContextScheduler:
    """Kernel-like scheduler for per-agent context budget allocation."""

    def __init__(
        self,
        total_budget: int = 8000,
        lookup_ratio: float = 0.90,
        warn_threshold: float = 0.85,
    ) -> None:
        if total_budget < 1:
            raise ValueError("total_budget must be positive")
        if not 0.0 < lookup_ratio < 1.0:
            raise ValueError("lookup_ratio must be between 0 and 1 exclusive")
        if not 0.0 < warn_threshold <= 1.0:
            raise ValueError("warn_threshold must be in (0, 1]")

        self.total_budget = total_budget
        self.lookup_ratio = lookup_ratio
        self.warn_threshold = warn_threshold
        self._active: dict[str, UsageRecord] = {}
        self._history: list[UsageRecord] = []
        self._signal_handlers: dict[AgentSignal, list[Callable[[str, AgentSignal], None]]] = {
            signal: [] for signal in AgentSignal
        }

    def allocate(
        self,
        agent_id: str,
        task: str,
        priority: ContextPriority = ContextPriority.NORMAL,
        max_tokens: int | None = None,
    ) -> ContextWindow:
        """Allocate a context window for an agent."""
        if max_tokens is not None and max_tokens < 1:
            raise ValueError("max_tokens must be positive")

        available = self.available_tokens
        desired = min(
            max_tokens if max_tokens is not None else int(self.total_budget * (0.25 + 0.25 * priority.value)),
            available,
        )
        if max_tokens is None:
            minimum = min(_MIN_CONTEXT[priority], available)
            allocated = max(minimum, desired)
        else:
            allocated = desired

        lookup = int(allocated * self.lookup_ratio)
        window = ContextWindow(
            agent_id=agent_id,
            task=task,
            lookup_budget=lookup,
            reasoning_budget=allocated - lookup,
            total=allocated,
        )
        self._active[agent_id] = UsageRecord(agent_id=agent_id, window=window)
        self._emit(AgentSignal.SIGRESUME, agent_id)
        return window

    def record_usage(
        self,
        agent_id: str,
        lookup_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> UsageRecord:
        """Record token usage and emit warning/stop signals at thresholds."""
        if lookup_tokens < 0 or reasoning_tokens < 0:
            raise ValueError("token usage must be non-negative")
        record = self._active.get(agent_id)
        if record is None:
            raise KeyError(f"No active allocation for agent {agent_id}")
        if record.stopped:
            raise BudgetExceeded(agent_id, record.window.total, record.total_used)

        record.lookup_used += lookup_tokens
        record.reasoning_used += reasoning_tokens
        if record.utilization >= 1.0:
            record.stopped = True
            record.stop_reason = "budget_exceeded"
            self._emit(AgentSignal.SIGSTOP, agent_id)
            raise BudgetExceeded(agent_id, record.window.total, record.total_used)
        if record.utilization >= self.warn_threshold:
            self._emit(AgentSignal.SIGWARN, agent_id)
        return record

    def release(self, agent_id: str) -> UsageRecord | None:
        """Release an allocation and move it to history."""
        record = self._active.pop(agent_id, None)
        if record is not None:
            self._history.append(record)
        return record

    def get_usage(self, agent_id: str) -> UsageRecord | None:
        return self._active.get(agent_id)

    def on_signal(self, signal: AgentSignal, handler: Callable[[str, AgentSignal], None]) -> None:
        self._signal_handlers[signal].append(handler)

    @property
    def active_agents(self) -> list[str]:
        return list(self._active)

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def available_tokens(self) -> int:
        used = sum(record.window.total for record in self._active.values())
        return max(0, self.total_budget - used)

    @property
    def utilization(self) -> float:
        allocated = sum(record.window.total for record in self._active.values())
        return allocated / self.total_budget if self.total_budget else 0.0

    def get_health_report(self) -> dict[str, Any]:
        return {
            "total_budget": self.total_budget,
            "available": self.available_tokens,
            "utilization": round(self.utilization, 3),
            "active_agents": self.active_count,
            "lookup_ratio": self.lookup_ratio,
            "agents": {
                agent_id: {
                    "task": record.window.task,
                    "allocated": record.window.total,
                    "used": record.total_used,
                    "remaining": record.remaining,
                    "stopped": record.stopped,
                }
                for agent_id, record in self._active.items()
            },
            "history_count": len(self._history),
        }

    def _emit(self, signal: AgentSignal, agent_id: str) -> None:
        for handler in self._signal_handlers[signal]:
            try:
                handler(agent_id, signal)
            except Exception:
                pass

