"""MAF (Microsoft Agent Framework) adapter — middleware list factory."""

import sys
from typing import Any

from policy_engine.audit import audit
from policy_engine.kernel import BaseKernel
from policy_engine.policy import GovernancePolicy, PolicyRequest


def _extract_tool_name(context: Any) -> str | None:
    return getattr(getattr(context, "function_call", None), "name", None)


def _extract_payload(context: Any) -> str:
    for attr in ("prompt", "input", "messages"):
        value = getattr(context, attr, None)
        if value:
            return str(value)
    return ""


def _effective_policy(
    policy: GovernancePolicy | None,
    allowed_tools: list[str] | None,
    denied_tools: list[str] | None,
    agent_id: str,
) -> GovernancePolicy:
    if policy is None:
        return GovernancePolicy(
            name=f"{agent_id}-tools",
            allowed_tools=allowed_tools,
            blocked_tools=denied_tools,
            max_tool_calls=sys.maxsize,
        )
    if allowed_tools is None and denied_tools is None:
        return policy
    return GovernancePolicy(
        name=policy.name,
        blocked_patterns=policy.blocked_patterns,
        max_tool_calls=policy.max_tool_calls,
        require_human_approval=policy.require_human_approval,
        allowed_tools=allowed_tools if allowed_tools is not None else policy.allowed_tools,
        blocked_tools=denied_tools if denied_tools is not None else policy.blocked_tools,
    )


def create_governance_middleware(
    allowed_tools: list[str] | None = None,
    denied_tools: list[str] | None = None,
    agent_id: str = "policy-engine-maf",
    enable_rogue_detection: bool = False,
    *,
    policy: GovernancePolicy | None = None,
) -> list[Any]:
    """Return a list of MAF middleware callables enforcing tool allow/deny.

    With no policy or allow/deny lists, returns an empty list (no per-call
    gating); the demo still records audit events at the wrapper level.
    """
    stack: list[Any] = []
    if policy is not None or allowed_tools or denied_tools:
        kernel = BaseKernel(
            _effective_policy(policy, allowed_tools, denied_tools, agent_id)
        )
        ctx = kernel.create_context(agent_id)

        async def _policy_gate(context, next_):
            tool_name = _extract_tool_name(context)
            decision = kernel.evaluate(
                ctx,
                PolicyRequest(
                    payload=_extract_payload(context),
                    tool_name=tool_name,
                    phase="tool_call" if tool_name else "pre_execute",
                ),
            )
            if not decision.allowed:
                audit(
                    "maf",
                    "policy_gate",
                    "BLOCKED",
                    f"agent={agent_id} reason={decision.reason or 'blocked'}",
                    decision=decision,
                )
                raise PermissionError(decision.reason or "blocked")
            return await next_(context)

        stack.append(_policy_gate)

    if enable_rogue_detection:
        async def _rogue_gate(context, next_):
            return await next_(context)

        stack.append(_rogue_gate)

    return stack
