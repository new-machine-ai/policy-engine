"""Claude Agent SDK adapter — hook factories for UserPromptSubmit, PreToolUse, PostToolUse.

The Claude Agent SDK uses HookMatcher callbacks rather than a kernel object.
This module ships pure-function helpers that close over a GovernancePolicy
(or an externally-supplied BaseKernel/ExecutionContext for shared state) and
return the async hook callables the SDK expects.
"""

import json
from typing import Any, Callable

from policy_engine.audit import audit
from policy_engine.context import ExecutionContext
from policy_engine.kernel import BaseKernel
from policy_engine.policy import GovernancePolicy, PolicyRequest

__all__ = [
    "make_user_prompt_hook",
    "make_pre_tool_use_hook",
    "make_post_tool_use_hook",
]


def _resolve_kernel_ctx(
    policy: GovernancePolicy,
    kernel: BaseKernel | None,
    ctx: ExecutionContext | None,
) -> tuple[BaseKernel, ExecutionContext]:
    if kernel is None:
        kernel = BaseKernel(policy)
    if ctx is None:
        ctx = kernel.create_context("claude")
    return kernel, ctx


def _stringify_tool_input(tool_input: Any) -> str:
    if isinstance(tool_input, str):
        return tool_input
    try:
        return json.dumps(tool_input, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(tool_input)


def make_user_prompt_hook(
    policy: GovernancePolicy,
    *,
    kernel: BaseKernel | None = None,
    ctx: ExecutionContext | None = None,
) -> Callable:
    kernel, ctx = _resolve_kernel_ctx(policy, kernel, ctx)

    async def gov_hook(input_data: Any, tool_use_id: Any, context: Any) -> dict:
        prompt = input_data.get("prompt", "") if isinstance(input_data, dict) else ""
        decision = kernel.evaluate(
            ctx,
            PolicyRequest(payload=prompt, phase="UserPromptSubmit"),
        )
        if not decision.allowed:
            detail = decision.reason or "blocked"
            audit(
                "claude",
                "UserPromptSubmit",
                "BLOCKED",
                detail,
                decision=decision,
            )
            if decision.matched_pattern is not None:
                reason = f"Blocked pattern: {decision.matched_pattern}"
            else:
                reason = detail
            return {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        audit("claude", "UserPromptSubmit", "ALLOWED", decision=decision)
        return {}

    return gov_hook


def make_pre_tool_use_hook(
    policy: GovernancePolicy,
    *,
    kernel: BaseKernel | None = None,
    ctx: ExecutionContext | None = None,
) -> Callable:
    kernel, ctx = _resolve_kernel_ctx(policy, kernel, ctx)

    async def gov_hook(input_data: Any, tool_use_id: Any, context: Any) -> dict:
        if not isinstance(input_data, dict):
            return {}
        tool_name = input_data.get("tool_name") or None
        payload = _stringify_tool_input(input_data.get("tool_input", ""))
        decision = kernel.evaluate(
            ctx,
            PolicyRequest(
                payload=payload,
                tool_name=tool_name,
                phase="PreToolUse",
            ),
        )
        if not decision.allowed:
            detail = decision.reason or "blocked"
            audit(
                "claude",
                "PreToolUse",
                "BLOCKED",
                detail,
                decision=decision,
            )
            if decision.matched_pattern is not None:
                reason = f"Blocked pattern: {decision.matched_pattern}"
            else:
                reason = detail
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        detail = f"tool={tool_name}" if tool_name else ""
        audit("claude", "PreToolUse", "ALLOWED", detail, decision=decision)
        return {}

    return gov_hook


def make_post_tool_use_hook(
    policy: GovernancePolicy,
    *,
    kernel: BaseKernel | None = None,
    ctx: ExecutionContext | None = None,
) -> Callable:
    # PostToolUse is informational: it fires after execution, so it cannot
    # block. We don't run kernel.evaluate (that would consume a call slot
    # for an event that wasn't a real pre-execution gate). Just record the
    # observed tool call so the unified audit trail has full coverage.
    _ = _resolve_kernel_ctx(policy, kernel, ctx)  # validate policy; share noop

    async def gov_hook(input_data: Any, tool_use_id: Any, context: Any) -> dict:
        if not isinstance(input_data, dict):
            return {}
        tool_name = input_data.get("tool_name") or None
        detail = f"tool={tool_name}" if tool_name else ""
        audit(
            "claude",
            "PostToolUse",
            "ALLOWED",
            detail,
            policy=policy.name,
            tool_name=tool_name,
        )
        return {}

    return gov_hook
