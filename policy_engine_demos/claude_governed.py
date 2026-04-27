"""Claude Agent SDK — full agent-loop demo wired to policy_engine.

Exercises the SDK surface end-to-end while routing every governance
decision through the shared BaseKernel + audit log:

  Phase 1  Build a shared kernel + ExecutionContext for all three hooks
  Phase 2  Configure ClaudeAgentOptions (allowed_tools, setting_sources=[],
           max_turns, max_budget_usd, effort, hooks)
  Phase 3  Allowed multi-turn flow via ClaudeSDKClient (auto session_id)
  Phase 4  Resume + fork the captured session via standalone query()
  Phase 5  Blocked flow — UserPromptSubmit hook denies a prompt that
           contains a POLICY.blocked_patterns substring
  Phase 6  Per-framework audit summary

NOTE: cannot run inside another Claude Code session — the SDK refuses
nested sessions. Run from a regular shell with CLAUDECODE unset.
"""

import asyncio
import os
from pathlib import Path

from _shared import AUDIT, POLICY, audit, step


def _claude_auth_present() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return True
    if (Path.home() / ".claude" / ".credentials.json").exists():
        return True
    return False


def _format_cost(value: float | None) -> str:
    return f"${value:.4f}" if value is not None else "N/A"


def _tool_names_in_message(msg) -> list[str]:
    names: list[str] = []
    inner = getattr(msg, "message", None)
    blocks = getattr(inner, "content", None) or getattr(msg, "content", None) or []
    for block in blocks:
        block_type = getattr(block, "type", None) or (
            block.get("type") if isinstance(block, dict) else None
        )
        if block_type == "tool_use":
            name = getattr(block, "name", None) or (
                block.get("name") if isinstance(block, dict) else None
            )
            if name:
                names.append(name)
    return names


async def _drain(stream) -> dict:
    """Iterate an async message stream; return summary of the final result."""
    summary = {
        "session_id": None,
        "subtype": None,
        "cost": None,
        "num_turns": None,
        "result_text": None,
    }
    async for msg in stream:
        msg_type = type(msg).__name__
        if msg_type == "AssistantMessage":
            tools = _tool_names_in_message(msg)
            blocks = (
                len(getattr(getattr(msg, "message", None), "content", []) or [])
                or len(getattr(msg, "content", []) or [])
            )
            tool_str = f", tools={tools}" if tools else ""
            step("claude", f"AssistantMessage — {blocks} blocks{tool_str}")
        elif msg_type == "ResultMessage" or getattr(msg, "subtype", None) in (
            "success",
            "error_max_turns",
            "error_max_budget_usd",
            "error_during_execution",
            "error_max_structured_output_retries",
        ):
            summary["session_id"] = getattr(msg, "session_id", None)
            summary["subtype"] = getattr(msg, "subtype", None)
            summary["cost"] = getattr(msg, "total_cost_usd", None)
            summary["num_turns"] = getattr(msg, "num_turns", None)
            summary["result_text"] = getattr(msg, "result", None)
            step(
                "claude",
                f"ResultMessage subtype={summary['subtype']} "
                f"turns={summary['num_turns']} cost={_format_cost(summary['cost'])}",
            )
    return summary


async def main() -> None:
    if os.environ.get("CLAUDECODE"):
        print("[skip] cannot run inside a Claude Code session (CLAUDECODE is set)")
        return

    step("claude", "Importing claude_agent_sdk and the policy_engine adapter.")
    from claude_agent_sdk import (
        ClaudeAgentOptions,
        ClaudeSDKClient,
        HookMatcher,
        query,
    )

    from policy_engine.adapters.claude import (
        make_post_tool_use_hook,
        make_pre_tool_use_hook,
        make_user_prompt_hook,
    )
    from policy_engine.kernel import BaseKernel

    if not _claude_auth_present():
        print("[skip] needs Claude auth (subscription login or ANTHROPIC_API_KEY)")
        return

    # Phase 1 — shared governance state across all three hooks.
    step("claude", "Phase 1 — building shared BaseKernel + ExecutionContext.")
    kernel = BaseKernel(POLICY)
    ctx = kernel.create_context("claude")
    user_prompt_hook = make_user_prompt_hook(POLICY, kernel=kernel, ctx=ctx)
    pre_tool_hook = make_pre_tool_use_hook(POLICY, kernel=kernel, ctx=ctx)
    post_tool_hook = make_post_tool_use_hook(POLICY, kernel=kernel, ctx=ctx)

    # Phase 2 — pin SDK options that the docs spotlight.
    step(
        "claude",
        "Phase 2 — ClaudeAgentOptions: allowed_tools=[Read,Glob,Grep], "
        "setting_sources=[], max_turns=5, max_budget_usd=0.50, effort=low.",
    )
    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Glob", "Grep"],
        setting_sources=[],  # don't load host CLAUDE.md / skills / hooks
        max_turns=5,
        max_budget_usd=0.50,
        permission_mode="default",
        system_prompt=(
            "You help summarize the policy_engine_demos directory. "
            "Use Glob, Read, and Grep only. Be terse."
        ),
        hooks={
            "UserPromptSubmit": [HookMatcher(hooks=[user_prompt_hook])],
            "PreToolUse": [HookMatcher(hooks=[pre_tool_hook])],
            "PostToolUse": [HookMatcher(hooks=[post_tool_hook])],
        },
    )
    # `effort` is a newer field; pass it via setattr so older SDK versions
    # that don't know it don't crash on construction.
    if hasattr(options, "effort"):
        try:
            setattr(options, "effort", "low")
        except Exception:
            pass

    captured_session: str | None = None
    fork_session: str | None = None
    total_cost = 0.0

    # Phase 3 — multi-turn allowed flow. ClaudeSDKClient threads session_id
    # automatically across queries on the same client.
    step("claude", "Phase 3 — ClaudeSDKClient multi-turn allowed flow.")
    async with ClaudeSDKClient(options=options) as client:
        await client.query(
            "List the Python demo files in this directory using Glob."
        )
        first = await _drain(client.receive_response())
        captured_session = first["session_id"]
        if first["cost"]:
            total_cost += first["cost"]

        await client.query(
            "Read langchain_governed.py and tell me which framework it targets in one sentence."
        )
        second = await _drain(client.receive_response())
        if second["cost"]:
            total_cost += second["cost"]

    audit(
        "claude",
        "phase3_session",
        "ALLOWED",
        f"session_id={captured_session}",
        policy=POLICY.name,
    )

    # Phase 4 — resume the captured session, then fork it.
    if captured_session:
        step("claude", f"Phase 4a — resume session {captured_session[:8]}...")
        resume_options = ClaudeAgentOptions(
            allowed_tools=["Read", "Glob", "Grep"],
            setting_sources=[],
            max_turns=2,
            permission_mode="default",
            resume=captured_session,
            hooks={
                "UserPromptSubmit": [HookMatcher(hooks=[user_prompt_hook])],
                "PreToolUse": [HookMatcher(hooks=[pre_tool_hook])],
                "PostToolUse": [HookMatcher(hooks=[post_tool_hook])],
            },
        )
        resume_summary = await _drain(
            query(
                prompt="Summarize what you learned about langchain_governed.py.",
                options=resume_options,
            )
        )
        if resume_summary["cost"]:
            total_cost += resume_summary["cost"]

        step("claude", "Phase 4b — fork from the same session into an alternate branch.")
        fork_options = ClaudeAgentOptions(
            allowed_tools=["Read", "Glob", "Grep"],
            setting_sources=[],
            max_turns=2,
            permission_mode="default",
            resume=captured_session,
            fork_session=True,
            hooks={
                "UserPromptSubmit": [HookMatcher(hooks=[user_prompt_hook])],
                "PreToolUse": [HookMatcher(hooks=[pre_tool_hook])],
                "PostToolUse": [HookMatcher(hooks=[post_tool_hook])],
            },
        )
        fork_summary = await _drain(
            query(
                prompt="Alternative summary: focus on the seam between the demo and policy_engine.",
                options=fork_options,
            )
        )
        fork_session = fork_summary["session_id"]
        if fork_summary["cost"]:
            total_cost += fork_summary["cost"]
        audit(
            "claude",
            "phase4_fork",
            "ALLOWED",
            f"fork={fork_session}",
            policy=POLICY.name,
        )

    # Phase 5 — blocked flow. The prompt contains a POLICY.blocked_patterns
    # substring; UserPromptSubmit must deny before any tool runs.
    step("claude", "Phase 5 — blocked prompt should be denied at UserPromptSubmit.")
    blocked_options = ClaudeAgentOptions(
        allowed_tools=["Read", "Glob", "Grep"],
        setting_sources=[],
        max_turns=2,
        permission_mode="default",
        hooks={
            "UserPromptSubmit": [HookMatcher(hooks=[user_prompt_hook])],
            "PreToolUse": [HookMatcher(hooks=[pre_tool_hook])],
            "PostToolUse": [HookMatcher(hooks=[post_tool_hook])],
        },
    )
    blocked_summary = await _drain(
        query(
            prompt="Please run rm -rf on the build cache to clean up.",
            options=blocked_options,
        )
    )
    if blocked_summary["cost"]:
        total_cost += blocked_summary["cost"]

    # Phase 6 — per-framework audit summary.
    step("claude", "Phase 6 — audit summary.")
    claude_events = [e for e in AUDIT if e["framework"] == "claude"]
    by_phase: dict[str, dict[str, int]] = {}
    for e in claude_events:
        by_phase.setdefault(e["phase"], {"ALLOWED": 0, "BLOCKED": 0})
        by_phase[e["phase"]][e["status"]] = by_phase[e["phase"]].get(e["status"], 0) + 1

    print(f"  Total Claude audit events  : {len(claude_events)}")
    for phase, counts in sorted(by_phase.items()):
        print(f"    {phase:<22} ALLOWED={counts.get('ALLOWED', 0)} BLOCKED={counts.get('BLOCKED', 0)}")
    print(f"  Captured session_id        : {captured_session}")
    print(f"  Forked session_id          : {fork_session}")
    print(f"  Total cost across phases   : {_format_cost(total_cost) if total_cost else 'N/A'}")
    print(f"  ctx.call_count (shared)    : {ctx.call_count} / {POLICY.max_tool_calls}")


if __name__ == "__main__":
    import _shared  # noqa: F401

    asyncio.run(main())
