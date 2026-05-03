# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Budget tracking for tokens, cost, duration, calls, and retries."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class BudgetPolicy:
    """Resource consumption limits for a governed task."""

    max_tokens: int | None = None
    max_tool_calls: int | None = None
    max_cost_usd: float | None = None
    max_duration_seconds: float | None = None
    max_retries: int | None = None
    warning_threshold: float = 0.8

    def __post_init__(self) -> None:
        for name, value in (
            ("max_tokens", self.max_tokens),
            ("max_tool_calls", self.max_tool_calls),
            ("max_retries", self.max_retries),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")
        for name, value in (
            ("max_cost_usd", self.max_cost_usd),
            ("max_duration_seconds", self.max_duration_seconds),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")
        if not 0 <= self.warning_threshold <= 1:
            raise ValueError("warning_threshold must be between 0 and 1")


@dataclass(frozen=True)
class BudgetStatus:
    """Snapshot of budget state."""

    exceeded: bool
    warning: bool
    reasons: list[str]
    remaining: dict[str, int | float | None]
    utilization: dict[str, float | None]

    def to_dict(self) -> dict[str, object]:
        return {
            "exceeded": self.exceeded,
            "warning": self.warning,
            "reasons": list(self.reasons),
            "remaining": dict(self.remaining),
            "utilization": dict(self.utilization),
        }


@dataclass
class BudgetTracker:
    """Tracks resource consumption against a budget policy."""

    policy: BudgetPolicy
    tokens_used: int = 0
    tool_calls_used: int = 0
    cost_usd_used: float = 0.0
    duration_seconds_used: float = 0.0
    retries_used: int = 0

    def record_tokens(self, count: int) -> None:
        _require_non_negative(count, "count")
        self.tokens_used += count

    def record_tool_call(self, count: int = 1) -> None:
        _require_non_negative(count, "count")
        self.tool_calls_used += count

    def record_cost(self, amount: float) -> None:
        _require_non_negative(amount, "amount")
        self.cost_usd_used += amount

    def record_duration(self, seconds: float) -> None:
        _require_non_negative(seconds, "seconds")
        self.duration_seconds_used += seconds

    def record_retry(self, count: int = 1) -> None:
        _require_non_negative(count, "count")
        self.retries_used += count

    def status(self) -> BudgetStatus:
        reasons = self.exceeded_reasons()
        utilization = self.utilization()
        warning = any(
            value is not None and value >= self.policy.warning_threshold
            for value in utilization.values()
        )
        return BudgetStatus(
            exceeded=bool(reasons),
            warning=warning,
            reasons=reasons,
            remaining=self.remaining(),
            utilization=utilization,
        )

    def is_exceeded(self) -> bool:
        return bool(self.exceeded_reasons())

    def exceeded_reasons(self) -> list[str]:
        return self._reasons_for(
            tokens=self.tokens_used,
            tool_calls=self.tool_calls_used,
            cost_usd=self.cost_usd_used,
            duration_seconds=self.duration_seconds_used,
            retries=self.retries_used,
        )

    def would_exceed(
        self,
        *,
        tokens: int = 0,
        tool_calls: int = 0,
        cost_usd: float = 0.0,
        duration_seconds: float = 0.0,
        retries: int = 0,
    ) -> list[str]:
        return self._reasons_for(
            tokens=self.tokens_used + tokens,
            tool_calls=self.tool_calls_used + tool_calls,
            cost_usd=self.cost_usd_used + cost_usd,
            duration_seconds=self.duration_seconds_used + duration_seconds,
            retries=self.retries_used + retries,
        )

    def remaining(self) -> dict[str, int | float | None]:
        return {
            "tokens": _remaining(self.policy.max_tokens, self.tokens_used),
            "tool_calls": _remaining(self.policy.max_tool_calls, self.tool_calls_used),
            "cost_usd": _remaining(self.policy.max_cost_usd, self.cost_usd_used),
            "duration_seconds": _remaining(self.policy.max_duration_seconds, self.duration_seconds_used),
            "retries": _remaining(self.policy.max_retries, self.retries_used),
        }

    def utilization(self) -> dict[str, float | None]:
        return {
            "tokens": _ratio(self.tokens_used, self.policy.max_tokens),
            "tool_calls": _ratio(self.tool_calls_used, self.policy.max_tool_calls),
            "cost_usd": _ratio(self.cost_usd_used, self.policy.max_cost_usd),
            "duration_seconds": _ratio(self.duration_seconds_used, self.policy.max_duration_seconds),
            "retries": _ratio(self.retries_used, self.policy.max_retries),
        }

    def _reasons_for(
        self,
        *,
        tokens: int,
        tool_calls: int,
        cost_usd: float,
        duration_seconds: float,
        retries: int,
    ) -> list[str]:
        reasons: list[str] = []
        policy = self.policy
        if policy.max_tokens is not None and tokens > policy.max_tokens:
            reasons.append(f"tokens: {tokens}/{policy.max_tokens}")
        if policy.max_tool_calls is not None and tool_calls > policy.max_tool_calls:
            reasons.append(f"tool_calls: {tool_calls}/{policy.max_tool_calls}")
        if policy.max_cost_usd is not None and cost_usd > policy.max_cost_usd:
            reasons.append(f"cost_usd: {cost_usd:.4f}/{policy.max_cost_usd:.4f}")
        if policy.max_duration_seconds is not None and duration_seconds > policy.max_duration_seconds:
            reasons.append(f"duration_seconds: {duration_seconds:.2f}/{policy.max_duration_seconds:.2f}")
        if policy.max_retries is not None and retries > policy.max_retries:
            reasons.append(f"retries: {retries}/{policy.max_retries}")
        return reasons


@dataclass(frozen=True)
class TokenBudgetStatus:
    """Snapshot of one agent's token budget status."""

    used: int
    limit: int
    remaining: int
    percentage: float
    is_warning: bool
    is_exceeded: bool

    def to_dict(self) -> dict[str, int | float | bool]:
        return {
            "used": self.used,
            "limit": self.limit,
            "remaining": self.remaining,
            "percentage": self.percentage,
            "is_warning": self.is_warning,
            "is_exceeded": self.is_exceeded,
        }


@dataclass
class _AgentUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    warning_emitted: bool = False


class TokenBudgetTracker:
    """Thread-safe per-agent token budget tracker."""

    def __init__(
        self,
        max_tokens: int = 4096,
        warning_threshold: float = 0.8,
        on_warning: Callable[[str, TokenBudgetStatus], None] | None = None,
    ) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if not 0 <= warning_threshold <= 1:
            raise ValueError("warning_threshold must be between 0 and 1")
        self._max_tokens = max_tokens
        self._warning_threshold = warning_threshold
        self._on_warning = on_warning
        self._lock = threading.Lock()
        self._usage: dict[str, _AgentUsage] = {}

    def record_usage(self, agent_id: str, prompt_tokens: int, completion_tokens: int) -> TokenBudgetStatus:
        _require_non_negative(prompt_tokens, "prompt_tokens")
        _require_non_negative(completion_tokens, "completion_tokens")
        with self._lock:
            usage = self._usage.setdefault(agent_id, _AgentUsage())
            usage.prompt_tokens += prompt_tokens
            usage.completion_tokens += completion_tokens
            usage.total_tokens += prompt_tokens + completion_tokens
            status = self._build_status(usage)
            should_warn = status.is_warning and not usage.warning_emitted
            if should_warn:
                usage.warning_emitted = True
        if should_warn and self._on_warning is not None:
            self._on_warning(agent_id, status)
        return status

    def get_usage(self, agent_id: str) -> TokenBudgetStatus:
        with self._lock:
            return self._build_status(self._usage.get(agent_id, _AgentUsage()))

    def check_budget(self, agent_id: str) -> TokenBudgetStatus:
        return self.get_usage(agent_id)

    def reset(self, agent_id: str) -> None:
        with self._lock:
            self._usage.pop(agent_id, None)

    def format_status(self, agent_id: str) -> str:
        status = self.get_usage(agent_id)
        filled = min(10, round(status.percentage * 10))
        bar = "#" * filled + "-" * (10 - filled)
        return f"[{bar}] {round(status.percentage * 100)}% ({status.used:,}/{status.limit:,} tokens)"

    def _build_status(self, usage: _AgentUsage) -> TokenBudgetStatus:
        used = usage.total_tokens
        remaining = max(0, self._max_tokens - used)
        percentage = used / self._max_tokens if self._max_tokens else 0.0
        return TokenBudgetStatus(
            used=used,
            limit=self._max_tokens,
            remaining=remaining,
            percentage=percentage,
            is_warning=percentage >= self._warning_threshold,
            is_exceeded=used >= self._max_tokens,
        )


def _require_non_negative(value: int | float, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _remaining(limit: int | float | None, used: int | float) -> int | float | None:
    if limit is None:
        return None
    value = limit - used
    return round(value, 4) if isinstance(value, float) else value


def _ratio(used: int | float, limit: int | float | None) -> float | None:
    if limit is None or limit == 0:
        return None
    return round(used / limit, 4)
