"""Claude Agent SDK adapter — UserPromptSubmit hook factory.

The Claude Agent SDK uses HookMatcher callbacks rather than a kernel object.
This module ships a pure-function helper that closes over a GovernancePolicy
and returns the async hook callable.
"""

from typing import Any, Callable

from policy_engine.audit import audit
from policy_engine.kernel import BaseKernel
from policy_engine.policy import GovernancePolicy, PolicyRequest

__all__ = ["make_user_prompt_hook"]


def make_user_prompt_hook(policy: GovernancePolicy) -> Callable:
    kernel = BaseKernel(policy)
    ctx = kernel.create_context("claude")

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
