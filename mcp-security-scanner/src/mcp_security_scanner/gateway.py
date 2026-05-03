# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Runtime MCP gateway backed by policy-engine decisions."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, time as datetime_time
from enum import Enum
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo

from policy_engine import BaseKernel, GovernancePolicy, PolicyRequest
from policy_engine.context import ExecutionContext

from .audit import AuditSink, InMemoryAuditSink


class ApprovalStatus(str, Enum):
    """Result of a human-approval check."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


@dataclass(frozen=True)
class GatewayDecision:
    """Structured runtime gateway decision."""

    allowed: bool
    reason: str
    policy: str
    agent_id: str
    tool_name: str
    payload_hash: str
    server_name: str = "unknown"
    approval_status: ApprovalStatus | None = None
    context_rule: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "policy": self.policy,
            "agent_id": self.agent_id,
            "tool_name": self.tool_name,
            "server_name": self.server_name,
            "payload_hash": self.payload_hash,
            "approval_status": self.approval_status.value if self.approval_status else None,
            "context_rule": self.context_rule,
        }


class GatewayRule(Protocol):
    """A contextual gateway rule evaluated after policy-engine allows a request."""

    name: str

    def evaluate(self, context: dict[str, Any]) -> tuple[bool, str | None]:
        """Return ``(allowed, reason)`` for one tool-call context."""


@dataclass(frozen=True)
class TimeWindowRule:
    """Allow selected tools only inside a local wall-clock time window."""

    name: str = "time_window"
    timezone: str = "UTC"
    start: str = "00:00"
    end: str = "23:59"
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)
    tools: tuple[str, ...] | None = None

    def evaluate(self, context: dict[str, Any]) -> tuple[bool, str | None]:
        tool_name = str(context.get("tool_name", ""))
        if self.tools is not None and tool_name not in self.tools:
            return True, None

        now = context.get("now")
        if now is None:
            now_dt = datetime.now(ZoneInfo(self.timezone))
        elif isinstance(now, datetime):
            now_dt = now.astimezone(ZoneInfo(self.timezone)) if now.tzinfo else now.replace(tzinfo=ZoneInfo(self.timezone))
        else:
            return False, f"{self.name}: invalid now value"

        if now_dt.weekday() not in self.weekdays:
            return False, f"{self.name}: outside allowed weekdays"

        current = now_dt.time().replace(second=0, microsecond=0)
        start = _parse_hhmm(self.start)
        end = _parse_hhmm(self.end)
        if start <= end:
            inside = start <= current <= end
        else:
            inside = current >= start or current <= end
        if inside:
            return True, None
        return False, f"{self.name}: outside allowed time window"


@dataclass(frozen=True)
class ParameterScopeRule:
    """Allow a parameter only when it matches values or prefixes."""

    parameter: str
    name: str = "parameter_scope"
    tools: tuple[str, ...] | None = None
    allowed_values: tuple[str, ...] | None = None
    allowed_prefixes: tuple[str, ...] = ()

    def evaluate(self, context: dict[str, Any]) -> tuple[bool, str | None]:
        tool_name = str(context.get("tool_name", ""))
        if self.tools is not None and tool_name not in self.tools:
            return True, None

        params = context.get("params")
        if not isinstance(params, dict) or self.parameter not in params:
            return False, f"{self.name}: missing parameter {self.parameter}"

        value = str(params[self.parameter])
        if self.allowed_values is not None and value not in self.allowed_values:
            return False, f"{self.name}: value for {self.parameter} is not allowed"
        if self.allowed_prefixes and not any(value.startswith(prefix) for prefix in self.allowed_prefixes):
            return False, f"{self.name}: value for {self.parameter} is outside allowed scope"
        return True, None


@dataclass
class MCPGateway:
    """Policy Enforcement Point for MCP tool calls.

    The gateway delegates the base allow/deny decision to ``policy-engine`` and
    layers MCP-specific context checks such as human approval and market-hours
    constraints around that PDP call.
    """

    policy: GovernancePolicy
    denied_tools: list[str] | None = None
    sensitive_tools: list[str] | None = None
    approval_callback: Callable[[str, str, dict[str, Any]], ApprovalStatus] | None = None
    context_rules: list[GatewayRule] = field(default_factory=list)
    audit_sink: AuditSink | None = None
    clock: Callable[[], float] = time.time

    def __post_init__(self) -> None:
        blocked = list(self.policy.blocked_tools or [])
        for tool in self.denied_tools or []:
            if tool not in blocked:
                blocked.append(tool)
        self._policy = replace(self.policy, blocked_tools=blocked or self.policy.blocked_tools)
        self._kernel = BaseKernel(self._policy)
        self._approval_free_kernel = BaseKernel(replace(self._policy, require_human_approval=False))
        self._contexts: dict[str, ExecutionContext] = {}
        self._lock = threading.Lock()
        self._audit_sink = self.audit_sink or InMemoryAuditSink()
        self._audit_log: list[dict[str, Any]] = []

    def evaluate_tool_call(
        self,
        agent_id: str,
        tool_name: str,
        params: dict[str, Any] | None = None,
        *,
        server_name: str = "unknown",
        now: datetime | None = None,
        extra_context: dict[str, Any] | None = None,
    ) -> GatewayDecision:
        """Evaluate whether an MCP tool call may execute."""
        params = params or {}
        payload = json.dumps(params, sort_keys=True, default=str)
        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        try:
            with self._lock:
                live_ctx = self._contexts.setdefault(
                    agent_id,
                    self._kernel.create_context(agent_id),
                )
                working_ctx = ExecutionContext(
                    name=live_ctx.name,
                    policy=live_ctx.policy,
                    call_count=live_ctx.call_count,
                )

                request = PolicyRequest(
                    payload=payload,
                    tool_name=tool_name,
                    phase="mcp_tool_call",
                )
                decision = self._kernel.evaluate(working_ctx, request)
                approval_status: ApprovalStatus | None = None

                if decision.requires_approval or tool_name in (self.sensitive_tools or []):
                    approval_status = self._request_approval(agent_id, tool_name, params)
                    if approval_status != ApprovalStatus.APPROVED:
                        result = self._decision(
                            False,
                            "human_approval_required"
                            if approval_status == ApprovalStatus.PENDING
                            else "human_approval_denied",
                            agent_id,
                            tool_name,
                            server_name,
                            payload_hash,
                            approval_status=approval_status,
                        )
                        self._record_audit(result)
                        return result
                    if decision.requires_approval:
                        working_ctx = ExecutionContext(
                            name=live_ctx.name,
                            policy=live_ctx.policy,
                            call_count=live_ctx.call_count,
                        )
                        decision = self._approval_free_kernel.evaluate(working_ctx, request)

                if not decision.allowed:
                    result = self._decision(
                        False,
                        decision.reason or "policy_denied",
                        agent_id,
                        tool_name,
                        server_name,
                        decision.payload_hash or payload_hash,
                        approval_status=approval_status,
                    )
                    self._record_audit(result)
                    return result

                rule_context: dict[str, Any] = {
                    "agent_id": agent_id,
                    "tool_name": tool_name,
                    "server_name": server_name,
                    "params": params,
                    "now": now,
                }
                if extra_context:
                    rule_context.update(extra_context)
                for rule in self.context_rules:
                    allowed, reason = rule.evaluate(rule_context)
                    if not allowed:
                        result = self._decision(
                            False,
                            reason or f"{rule.name}: denied",
                            agent_id,
                            tool_name,
                            server_name,
                            decision.payload_hash or payload_hash,
                            approval_status=approval_status,
                            context_rule=rule.name,
                        )
                        self._record_audit(result)
                        return result

                live_ctx.call_count = working_ctx.call_count
                result = self._decision(
                    True,
                    "allowed",
                    agent_id,
                    tool_name,
                    server_name,
                    decision.payload_hash or payload_hash,
                    approval_status=approval_status,
                )
                self._record_audit(result)
                return result
        except Exception:
            result = self._decision(
                False,
                "gateway_error_fail_closed",
                agent_id,
                tool_name,
                server_name,
                payload_hash,
            )
            self._record_audit(result)
            return result

    def intercept_tool_call(
        self,
        agent_id: str,
        tool_name: str,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> tuple[bool, str]:
        """AGT-compatible tuple interface."""
        decision = self.evaluate_tool_call(agent_id, tool_name, params, **kwargs)
        return decision.allowed, decision.reason

    @property
    def audit_log(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in self._audit_log]

    def get_agent_call_count(self, agent_id: str) -> int:
        ctx = self._contexts.get(agent_id)
        return ctx.call_count if ctx is not None else 0

    def reset_agent_budget(self, agent_id: str) -> None:
        with self._lock:
            ctx = self._contexts.setdefault(agent_id, self._kernel.create_context(agent_id))
            ctx.call_count = 0

    def _request_approval(
        self,
        agent_id: str,
        tool_name: str,
        params: dict[str, Any],
    ) -> ApprovalStatus:
        if self.approval_callback is None:
            return ApprovalStatus.PENDING
        try:
            status = self.approval_callback(agent_id, tool_name, params)
            return ApprovalStatus(status)
        except Exception:
            return ApprovalStatus.DENIED

    def _decision(
        self,
        allowed: bool,
        reason: str,
        agent_id: str,
        tool_name: str,
        server_name: str,
        payload_hash: str,
        *,
        approval_status: ApprovalStatus | None = None,
        context_rule: str | None = None,
    ) -> GatewayDecision:
        return GatewayDecision(
            allowed=allowed,
            reason=reason,
            policy=self._policy.name,
            agent_id=agent_id,
            tool_name=tool_name,
            server_name=server_name,
            payload_hash=payload_hash,
            approval_status=approval_status,
            context_rule=context_rule,
        )

    def _record_audit(self, decision: GatewayDecision) -> None:
        entry = {
            "timestamp": datetime.fromtimestamp(self.clock(), ZoneInfo("UTC")).isoformat(),
            "action": "tool_call",
            "policy": decision.policy,
            "agent_id": decision.agent_id,
            "tool_name": decision.tool_name,
            "server_name": decision.server_name,
            "allowed": decision.allowed,
            "reason": decision.reason,
            "payload_hash": decision.payload_hash,
            "approval_status": decision.approval_status.value if decision.approval_status else None,
            "context_rule": decision.context_rule,
        }
        self._audit_log.append(entry)
        self._audit_sink.record(entry)


def _parse_hhmm(value: str) -> datetime_time:
    hour_text, minute_text = value.split(":", 1)
    return datetime_time(hour=int(hour_text), minute=int(minute_text))

