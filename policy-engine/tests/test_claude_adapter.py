"""Tests for the Claude Agent SDK adapter hook factories.

These tests do not import claude_agent_sdk — they exercise the pure-Python
hook callables returned by the factories with synthetic input dicts.
"""

import asyncio
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from policy_engine import AUDIT, BaseKernel, GovernancePolicy, reset_audit  # noqa: E402
from policy_engine.adapters.claude import (  # noqa: E402
    make_post_tool_use_hook,
    make_pre_tool_use_hook,
    make_user_prompt_hook,
)


def _policy() -> GovernancePolicy:
    return GovernancePolicy(
        name="claude-test",
        blocked_patterns=["DROP TABLE", "rm -rf"],
        max_tool_calls=10,
        blocked_tools=["shell_exec"],
    )


def test_pre_tool_use_blocks_blocked_tool() -> None:
    reset_audit()
    hook = make_pre_tool_use_hook(_policy())
    result = asyncio.run(
        hook(
            {"tool_name": "shell_exec", "tool_input": {"command": "ls"}},
            None,
            None,
        )
    )
    output = result["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    assert output["permissionDecision"] == "deny"
    assert "blocked_tool:shell_exec" in output["permissionDecisionReason"]
    last = AUDIT[-1]
    assert last["framework"] == "claude"
    assert last["phase"] == "PreToolUse"
    assert last["status"] == "BLOCKED"
    assert last["tool_name"] == "shell_exec"
    assert "payload_hash" in last
    reset_audit()


def test_pre_tool_use_blocks_pattern_in_tool_input() -> None:
    reset_audit()
    hook = make_pre_tool_use_hook(_policy())
    result = asyncio.run(
        hook(
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/x"}},
            None,
            None,
        )
    )
    output = result["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert "Blocked pattern: rm -rf" == output["permissionDecisionReason"]
    last = AUDIT[-1]
    assert last["status"] == "BLOCKED"
    assert last["tool_name"] == "Bash"
    reset_audit()


def test_pre_tool_use_allows_safe_call_and_records() -> None:
    reset_audit()
    hook = make_pre_tool_use_hook(_policy())
    result = asyncio.run(
        hook(
            {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}},
            None,
            None,
        )
    )
    assert result == {}
    last = AUDIT[-1]
    assert last["phase"] == "PreToolUse"
    assert last["status"] == "ALLOWED"
    assert last["tool_name"] == "Read"
    reset_audit()


def test_pre_tool_use_handles_non_dict_input_gracefully() -> None:
    reset_audit()
    hook = make_pre_tool_use_hook(_policy())
    result = asyncio.run(hook("not a dict", None, None))
    assert result == {}
    assert AUDIT == []
    reset_audit()


def test_post_tool_use_records_allowed_without_evaluating() -> None:
    reset_audit()
    policy = _policy()
    kernel = BaseKernel(policy)
    ctx = kernel.create_context("claude")
    hook = make_post_tool_use_hook(policy, kernel=kernel, ctx=ctx)
    result = asyncio.run(
        hook(
            {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}},
            None,
            None,
        )
    )
    assert result == {}
    last = AUDIT[-1]
    assert last["phase"] == "PostToolUse"
    assert last["status"] == "ALLOWED"
    assert last["tool_name"] == "Read"
    # PostToolUse is informational; it must not consume a call slot.
    assert ctx.call_count == 0
    reset_audit()


def test_shared_kernel_enforces_max_tool_calls_across_hooks() -> None:
    reset_audit()
    policy = GovernancePolicy(
        name="claude-share",
        blocked_patterns=[],
        max_tool_calls=2,
    )
    kernel = BaseKernel(policy)
    ctx = kernel.create_context("claude")
    user_hook = make_user_prompt_hook(policy, kernel=kernel, ctx=ctx)
    pre_hook = make_pre_tool_use_hook(policy, kernel=kernel, ctx=ctx)

    # First call (UserPromptSubmit) consumes slot 1.
    asyncio.run(user_hook({"prompt": "hello"}, None, None))
    # Second call (PreToolUse) consumes slot 2 — still under the cap.
    asyncio.run(
        pre_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}},
            None,
            None,
        )
    )
    # Third call must be denied because cap was reached.
    result = asyncio.run(
        pre_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "/tmp/y"}},
            None,
            None,
        )
    )
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "max_tool_calls" in result["hookSpecificOutput"]["permissionDecisionReason"]
    assert AUDIT[-1]["status"] == "BLOCKED"
    reset_audit()
