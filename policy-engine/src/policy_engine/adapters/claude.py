"""Claude Agent SDK adapter — hook factories for every Python-supported event.

The Claude Agent SDK uses HookMatcher callbacks rather than a kernel object.
This module ships pure-function helpers that close over a GovernancePolicy
(or an externally-supplied BaseKernel/ExecutionContext for shared state) and
return the async hook callables the SDK expects.

Coverage: UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure,
Stop, SubagentStart, SubagentStop, PreCompact, PermissionRequest,
Notification — i.e. all ten hook events the Python SDK supports.
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
    "make_stop_hook",
    "make_subagent_start_hook",
    "make_subagent_stop_hook",
    "make_pre_compact_hook",
    "make_post_tool_failure_hook",
    "make_permission_request_hook",
    "make_notification_hook",
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


def make_stop_hook(
    policy: GovernancePolicy,
    *,
    kernel: BaseKernel | None = None,
    ctx: ExecutionContext | None = None,
) -> Callable:
    _ = _resolve_kernel_ctx(policy, kernel, ctx)

    async def gov_hook(input_data: Any, tool_use_id: Any, context: Any) -> dict:
        if not isinstance(input_data, dict):
            return {}
        detail = f"stop_hook_active={input_data.get('stop_hook_active', False)}"
        audit("claude", "Stop", "ALLOWED", detail, policy=policy.name)
        return {}

    return gov_hook


def make_subagent_start_hook(
    policy: GovernancePolicy,
    *,
    kernel: BaseKernel | None = None,
    ctx: ExecutionContext | None = None,
) -> Callable:
    _ = _resolve_kernel_ctx(policy, kernel, ctx)

    async def gov_hook(input_data: Any, tool_use_id: Any, context: Any) -> dict:
        if not isinstance(input_data, dict):
            return {}
        agent_id = input_data.get("agent_id") or "?"
        agent_type = input_data.get("agent_type") or "?"
        detail = f"agent_id={agent_id} agent_type={agent_type}"
        audit("claude", "SubagentStart", "ALLOWED", detail, policy=policy.name)
        return {}

    return gov_hook


def make_subagent_stop_hook(
    policy: GovernancePolicy,
    *,
    kernel: BaseKernel | None = None,
    ctx: ExecutionContext | None = None,
) -> Callable:
    _ = _resolve_kernel_ctx(policy, kernel, ctx)

    async def gov_hook(input_data: Any, tool_use_id: Any, context: Any) -> dict:
        if not isinstance(input_data, dict):
            return {}
        agent_id = input_data.get("agent_id") or "?"
        detail = f"agent_id={agent_id}"
        audit("claude", "SubagentStop", "ALLOWED", detail, policy=policy.name)
        return {}

    return gov_hook


def make_pre_compact_hook(
    policy: GovernancePolicy,
    *,
    kernel: BaseKernel | None = None,
    ctx: ExecutionContext | None = None,
) -> Callable:
    _ = _resolve_kernel_ctx(policy, kernel, ctx)

    async def gov_hook(input_data: Any, tool_use_id: Any, context: Any) -> dict:
        if not isinstance(input_data, dict):
            return {}
        trigger = input_data.get("trigger") or "?"
        detail = f"trigger={trigger}"
        audit("claude", "PreCompact", "ALLOWED", detail, policy=policy.name)
        return {}

    return gov_hook


def make_post_tool_failure_hook(
    policy: GovernancePolicy,
    *,
    kernel: BaseKernel | None = None,
    ctx: ExecutionContext | None = None,
) -> Callable:
    # PostToolUseFailure records a real tool error. Status is BLOCKED to
    # distinguish it from successful PostToolUse rows in the unified audit
    # trail. No kernel evaluation — the SDK already knows the call failed.
    _ = _resolve_kernel_ctx(policy, kernel, ctx)

    async def gov_hook(input_data: Any, tool_use_id: Any, context: Any) -> dict:
        if not isinstance(input_data, dict):
            return {}
        tool_name = input_data.get("tool_name") or None
        error = input_data.get("error") or input_data.get("error_message") or ""
        error_type = type(error).__name__ if not isinstance(error, str) else "str"
        detail_parts = []
        if tool_name:
            detail_parts.append(f"tool={tool_name}")
        if error:
            detail_parts.append(f"error_type={error_type}")
        detail = " ".join(detail_parts)
        audit(
            "claude",
            "PostToolUseFailure",
            "BLOCKED",
            detail,
            policy=policy.name,
            tool_name=tool_name,
            reason=str(error)[:200] if error else None,
        )
        return {}

    return gov_hook


def make_permission_request_hook(
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
                phase="PermissionRequest",
            ),
        )
        if not decision.allowed and not decision.requires_approval:
            detail = decision.reason or "blocked"
            audit(
                "claude",
                "PermissionRequest",
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
                    "hookEventName": "PermissionRequest",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        if decision.requires_approval:
            audit(
                "claude",
                "PermissionRequest",
                "ALLOWED",
                "requires_approval",
                decision=decision,
            )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": "policy requires human approval",
                }
            }
        detail = f"tool={tool_name}" if tool_name else ""
        audit("claude", "PermissionRequest", "ALLOWED", detail, decision=decision)
        return {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "permissionDecision": "allow",
                "permissionDecisionReason": "policy allows",
            }
        }

    return gov_hook


def make_notification_hook(
    policy: GovernancePolicy,
    *,
    kernel: BaseKernel | None = None,
    ctx: ExecutionContext | None = None,
) -> Callable:
    _ = _resolve_kernel_ctx(policy, kernel, ctx)

    async def gov_hook(input_data: Any, tool_use_id: Any, context: Any) -> dict:
        if not isinstance(input_data, dict):
            return {}
        ntype = (
            input_data.get("notification_type")
            or input_data.get("type")
            or "?"
        )
        message = input_data.get("message", "") or ""
        # Short messages go in detail; long ones get truncated. Audit module
        # handles the SHA-256 if a payload_hash is needed downstream.
        if len(message) <= 80:
            detail = f"type={ntype} msg={message!r}" if message else f"type={ntype}"
        else:
            detail = f"type={ntype} msg_len={len(message)}"
        audit("claude", "Notification", "ALLOWED", detail, policy=policy.name)
        return {}

    return gov_hook
