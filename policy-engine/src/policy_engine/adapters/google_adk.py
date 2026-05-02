"""Google ADK adapter -- callbacks and Runner plugin.

Seam: ``LlmAgent(..., **kernel.as_callbacks())`` accepts agent-level tool
callbacks, while ``Runner(..., plugins=[kernel.as_plugin()])`` accepts a
runner-scoped ADK ``BasePlugin``. Both surfaces delegate policy decisions to
``BaseKernel.evaluate``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from policy_engine.audit import audit
from policy_engine.kernel import BaseKernel
from policy_engine.policy import (
    GovernancePolicy,
    PolicyDecision,
    PolicyRequest,
    PolicyViolationError,
)

__all__ = [
    "GoogleADKAuditEvent",
    "GoogleADKKernel",
    "GoogleADKPolicyViolation",
    "GovernancePolicy",
    "PolicyViolationError",
]


@dataclass(frozen=True)
class GoogleADKAuditEvent:
    """Single Google ADK audit event without raw prompt/tool payloads."""

    timestamp: str
    event_type: str
    agent_name: str
    details: dict[str, Any]


class GoogleADKPolicyViolation(PolicyViolationError):
    """Policy violation shape that mirrors the Agent-OS Google ADK demo."""

    def __init__(
        self,
        policy_name: str,
        description: str,
        *,
        pattern: str | None = None,
        severity: str = "high",
    ) -> None:
        self.policy_name = policy_name
        self.description = description
        self.severity = severity
        super().__init__(description, pattern=pattern)


def _json_default(value: Any) -> Any:
    if hasattr(value, "__dict__"):
        return vars(value)
    return str(value)


def _payload_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, default=_json_default)
    except (TypeError, ValueError):
        return str(value)


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return _content_text(content.get("content") or content.get("parts"))
    if isinstance(content, list):
        return "\n".join(filter(None, (_content_text(item) for item in content)))

    parts = getattr(content, "parts", None)
    if parts is not None:
        return "\n".join(filter(None, (_content_text(part) for part in parts)))

    text = getattr(content, "text", None)
    if isinstance(text, str):
        return text
    return ""


def _llm_request_text(llm_request: Any) -> str:
    contents = getattr(llm_request, "contents", None)
    if contents is None and isinstance(llm_request, dict):
        contents = llm_request.get("contents")
    return _content_text(contents)


def _extract_tool_name(tool: Any, tool_context: Any, kwargs: dict[str, Any]) -> str:
    for value in (
        kwargs.get("tool_name"),
        getattr(tool, "name", None),
        getattr(tool_context, "tool_name", None),
    ):
        if value:
            return str(value)
    return "unknown"


def _extract_tool_args(args: Any, tool_context: Any, kwargs: dict[str, Any]) -> Any:
    if "tool_args" in kwargs:
        return kwargs["tool_args"]
    if "args" in kwargs:
        return kwargs["args"]
    if args is not None:
        return args
    value = getattr(tool_context, "tool_args", None)
    if value is not None:
        return value
    return {}


def _extract_agent_name(tool_context: Any, kwargs: dict[str, Any]) -> str:
    for value in (
        kwargs.get("agent_name"),
        getattr(tool_context, "agent_name", None),
    ):
        if value:
            return str(value)
    return "unknown"


class GoogleADKKernel(BaseKernel):
    """Governance kernel for Google ADK callbacks and Runner plugins."""

    framework = "google_adk"

    def __init__(
        self,
        policy: GovernancePolicy | None = None,
        *,
        max_budget: float | None = None,
        on_violation: Callable[[GoogleADKPolicyViolation], None] | None = None,
        name: str = "google-adk",
        max_tool_calls: int = 10,
        allowed_tools: list[str] | None = None,
        blocked_tools: list[str] | None = None,
        blocked_patterns: list[str] | None = None,
        require_human_approval: bool = False,
    ) -> None:
        effective_policy = policy or GovernancePolicy(
            name=name,
            blocked_patterns=blocked_patterns or [],
            max_tool_calls=max_tool_calls,
            require_human_approval=require_human_approval,
            allowed_tools=allowed_tools,
            blocked_tools=blocked_tools,
        )
        super().__init__(effective_policy)
        self.max_budget = max_budget
        self._budget_spent = 0.0
        self._on_violation = on_violation
        self._ctx = self.create_context("google-adk")
        self._audit_log: list[GoogleADKAuditEvent] = []
        self._violations: list[GoogleADKPolicyViolation] = []

    def as_callbacks(self) -> dict[str, Any]:
        """Return ADK agent-level callbacks for ``LlmAgent(..., **callbacks)``."""
        return {
            "before_tool_callback": self.before_tool_callback,
            "after_tool_callback": self.after_tool_callback,
        }

    get_callbacks = as_callbacks

    def as_plugin(self, name: str = "policy-engine-google-adk") -> Any:
        """Return a Google ADK ``BasePlugin`` backed by this kernel."""
        try:
            from google.adk.plugins.base_plugin import BasePlugin
        except ImportError as exc:
            raise ImportError(
                "The 'google-adk' package is required for Google ADK plugins. "
                "Install it with: pip install google-adk"
            ) from exc

        kernel = self

        class GovernancePlugin(BasePlugin):
            def __init__(self) -> None:
                super().__init__(name=name)

            async def before_model_callback(
                self,
                *,
                callback_context: Any,
                llm_request: Any,
            ) -> Any:
                agent_name = getattr(callback_context, "agent_name", "unknown")
                decision = kernel._evaluate(
                    "before_model",
                    str(agent_name),
                    payload=_llm_request_text(llm_request),
                )
                if not decision.allowed:
                    raise kernel._violation(decision)
                return None

            async def before_tool_callback(
                self,
                *,
                tool: Any,
                tool_args: dict[str, Any],
                tool_context: Any,
            ) -> dict[str, Any] | None:
                return kernel.before_tool_callback(
                    tool=tool,
                    tool_args=tool_args,
                    tool_context=tool_context,
                )

            async def after_tool_callback(
                self,
                *,
                tool: Any,
                tool_args: dict[str, Any],
                tool_context: Any,
                result: dict[str, Any],
            ) -> dict[str, Any] | None:
                return kernel.after_tool_callback(
                    tool=tool,
                    tool_args=tool_args,
                    tool_context=tool_context,
                    result=result,
                )

        return GovernancePlugin()

    def before_tool_callback(
        self,
        tool: Any = None,
        args: dict[str, Any] | None = None,
        tool_context: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """ADK before-tool callback.

        Supports ADK plugin callbacks (``tool_args=...``), ADK agent callbacks
        (``args=...``), and the direct quickstart shape
        (``tool_name=...``, ``tool_args=...``, ``agent_name=...``).
        """
        tool_name = _extract_tool_name(tool, tool_context, kwargs)
        agent_name = _extract_agent_name(tool_context, kwargs)
        tool_args = _extract_tool_args(args, tool_context, kwargs)
        payload = _payload_text(tool_args)

        budget_decision = self._check_budget(
            agent_name,
            payload=payload,
            tool_name=tool_name,
            cost=kwargs.get("cost", 1.0),
        )
        if budget_decision is not None:
            return {"error": str(self._violation(budget_decision))}

        decision = self._evaluate(
            "before_tool",
            agent_name,
            payload=payload,
            tool_name=tool_name,
        )
        if not decision.allowed:
            return {"error": str(self._violation(decision))}

        self._budget_spent += float(kwargs.get("cost", 1.0) or 0.0)
        return None

    def after_tool_callback(
        self,
        tool: Any = None,
        args: dict[str, Any] | None = None,
        tool_context: Any = None,
        tool_response: Any = None,
        result: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """ADK after-tool callback that scans tool output for blocked content."""
        tool_name = _extract_tool_name(tool, tool_context, kwargs)
        agent_name = _extract_agent_name(tool_context, kwargs)
        output = result if result is not None else tool_response
        if output is None and "tool_response" in kwargs:
            output = kwargs["tool_response"]
        payload = _payload_text(output)

        decision = self._evaluate(
            "after_tool",
            agent_name,
            payload=payload,
            tool_name=tool_name,
        )
        if not decision.allowed:
            return {"error": str(self._violation(decision))}
        return None

    def get_stats(self) -> dict[str, Any]:
        """Return adapter-local counters and policy metadata."""
        return {
            "tool_calls": self._ctx.call_count,
            "violations": len(self._violations),
            "audit_events": len(self._audit_log),
            "budget_spent": self._budget_spent,
            "budget_limit": self.max_budget,
            "policy": {
                "name": self.policy.name,
                "max_tool_calls": self.policy.max_tool_calls,
                "allowed_tools": self.policy.allowed_tools,
                "blocked_tools": self.policy.blocked_tools,
                "blocked_patterns": self.policy.blocked_patterns,
            },
        }

    def get_violations(self) -> list[GoogleADKPolicyViolation]:
        """Return collected policy violations."""
        return list(self._violations)

    def get_audit_log(self) -> list[GoogleADKAuditEvent]:
        """Return adapter-local audit events."""
        return list(self._audit_log)

    def _evaluate(
        self,
        phase: str,
        agent_name: str,
        *,
        payload: str,
        tool_name: str | None = None,
    ) -> PolicyDecision:
        decision = self.evaluate(
            self._ctx,
            PolicyRequest(payload=payload, tool_name=tool_name, phase=phase),
        )
        status = "ALLOWED" if decision.allowed else "BLOCKED"
        detail = decision.reason or (f"tool={tool_name}" if tool_name else agent_name)
        self._record(phase, agent_name, status, detail, decision)
        return decision

    def _check_budget(
        self,
        agent_name: str,
        *,
        payload: str,
        tool_name: str,
        cost: Any,
    ) -> PolicyDecision | None:
        if self.max_budget is None:
            return None
        numeric_cost = float(cost or 0.0)
        if self._budget_spent + numeric_cost <= self.max_budget:
            return None
        request = PolicyRequest(payload=payload, tool_name=tool_name, phase="budget")
        decision = PolicyDecision(
            allowed=False,
            reason="budget_exceeded",
            policy=self.policy.name,
            tool_name=tool_name,
            payload_hash=request.payload_sha256(),
            phase="budget",
        )
        self._record("budget", agent_name, "BLOCKED", "budget_exceeded", decision)
        return decision

    def _record(
        self,
        phase: str,
        agent_name: str,
        status: str,
        detail: str,
        decision: PolicyDecision,
    ) -> None:
        audit("google_adk", phase, status, detail, decision=decision)
        details: dict[str, Any] = {
            "phase": phase,
            "status": status,
            "policy": decision.policy,
        }
        if decision.reason:
            details["reason"] = decision.reason
        if decision.tool_name:
            details["tool"] = decision.tool_name
        if decision.payload_hash:
            details["payload_hash"] = decision.payload_hash
        self._audit_log.append(
            GoogleADKAuditEvent(
                timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                event_type=phase,
                agent_name=agent_name,
                details=details,
            )
        )

    def _violation(self, decision: PolicyDecision) -> GoogleADKPolicyViolation:
        error = GoogleADKPolicyViolation(
            decision.policy,
            decision.reason or "blocked",
            pattern=decision.matched_pattern,
        )
        self._violations.append(error)
        if self._on_violation is not None:
            self._on_violation(error)
        return error
