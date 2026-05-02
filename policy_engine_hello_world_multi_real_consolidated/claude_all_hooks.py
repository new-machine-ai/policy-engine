"""Claude Agent SDK — register every Python-supported hook factory.

Companion to claude_governed.py. Where claude_governed.py demonstrates the
agent-loop surface (multi-turn ClaudeSDKClient, resume, fork, cost), this
demo's job is the *hook* surface: it wires up all ten factories the adapter
ships, runs one short read-only query, and prints which hook events
actually fired during the session. Hooks that depend on specific SDK
behaviour (SubagentStart/Stop need a Task call; PreCompact needs context
compaction; PostToolUseFailure needs a tool error) won't necessarily fire
on every run — the demo proves the wiring; the audit summary at the end
shows what the SDK actually emitted.

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


async def _drain(stream) -> None:
    """Iterate an async message stream and step() the result subtype."""
    async for msg in stream:
        msg_type = type(msg).__name__
        if msg_type == "ResultMessage" or getattr(msg, "subtype", None) in (
            "success",
            "error_max_turns",
            "error_max_budget_usd",
            "error_during_execution",
            "error_max_structured_output_retries",
        ):
            step(
                "claude_all_hooks",
                f"ResultMessage subtype={getattr(msg, 'subtype', None)} "
                f"turns={getattr(msg, 'num_turns', None)}",
            )


async def main() -> None:
    if os.environ.get("CLAUDECODE"):
        print("[skip] cannot run inside a Claude Code session (CLAUDECODE is set)")
        return

    step(
        "claude_all_hooks",
        "Importing claude_agent_sdk and all ten hook factories.",
    )
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, query

    from policy_engine.adapters.claude import (
        make_notification_hook,
        make_permission_request_hook,
        make_post_tool_failure_hook,
        make_post_tool_use_hook,
        make_pre_compact_hook,
        make_pre_tool_use_hook,
        make_stop_hook,
        make_subagent_start_hook,
        make_subagent_stop_hook,
        make_user_prompt_hook,
    )
    from policy_engine.kernel import BaseKernel

    if not _claude_auth_present():
        print(
            "[skip] needs Claude auth (subscription login or ANTHROPIC_API_KEY)"
        )
        return

    # One shared kernel + ctx so max_tool_calls is enforced across every
    # hook event, not per-hook. Same pattern as claude_governed.py Phase 1.
    step(
        "claude_all_hooks",
        "Building shared BaseKernel + ExecutionContext.",
    )
    kernel = BaseKernel(POLICY)
    ctx = kernel.create_context("claude_all_hooks")

    # Build each factory once. Each hook closes over the same kernel/ctx.
    factories = {
        "UserPromptSubmit": make_user_prompt_hook,
        "PreToolUse": make_pre_tool_use_hook,
        "PostToolUse": make_post_tool_use_hook,
        "PostToolUseFailure": make_post_tool_failure_hook,
        "Stop": make_stop_hook,
        "SubagentStart": make_subagent_start_hook,
        "SubagentStop": make_subagent_stop_hook,
        "PreCompact": make_pre_compact_hook,
        "PermissionRequest": make_permission_request_hook,
        "Notification": make_notification_hook,
    }
    step(
        "claude_all_hooks",
        f"Instantiating {len(factories)} hook factories with shared kernel/ctx.",
    )
    hooks_dict = {
        event: [HookMatcher(hooks=[factory(POLICY, kernel=kernel, ctx=ctx)])]
        for event, factory in factories.items()
    }

    # Read-only allowlist + sealed setting_sources, same defensive posture as
    # claude_governed.py.
    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Glob", "Grep"],
        setting_sources=[],
        max_turns=3,
        permission_mode="default",
        system_prompt=(
            "You answer in one short sentence. Use Glob, Read, and Grep only."
        ),
        hooks=hooks_dict,
    )

    step(
        "claude_all_hooks",
        "Running a short query so the SDK can fire whichever hooks the "
        "session triggers.",
    )
    await _drain(
        query(
            prompt="List the .py files in this directory and tell me how many there are.",
            options=options,
        )
    )

    # Per-event summary — show which hooks the SDK actually emitted in this
    # run, so a reader can see at a glance which of the ten are wired-and-
    # firing vs wired-but-dormant (e.g. SubagentStart only fires if the
    # agent invokes Task).
    step("claude_all_hooks", "Per-hook audit summary.")
    rows = [e for e in AUDIT if e["framework"] == "claude"]
    by_phase: dict[str, dict[str, int]] = {}
    for e in rows:
        bucket = by_phase.setdefault(e["phase"], {"ALLOWED": 0, "BLOCKED": 0})
        bucket[e["status"]] = bucket.get(e["status"], 0) + 1

    print(f"  Hook factories registered  : {len(factories)} / 10")
    print(f"  Total Claude audit events  : {len(rows)}")
    print("  Hook events that fired     :")
    for event in factories:
        counts = by_phase.get(event)
        if counts is None:
            print(f"    {event:<22} (did not fire)")
        else:
            print(
                f"    {event:<22} ALLOWED={counts.get('ALLOWED', 0)} "
                f"BLOCKED={counts.get('BLOCKED', 0)}"
            )
    # Surface any phases that aren't standard SDK events (e.g. the bookkeeping
    # rows the demo itself records).
    bookkeeping = [p for p in by_phase if p not in factories]
    if bookkeeping:
        print("  Other audit rows (bookkeeping):")
        for p in sorted(bookkeeping):
            counts = by_phase[p]
            print(
                f"    {p:<22} ALLOWED={counts.get('ALLOWED', 0)} "
                f"BLOCKED={counts.get('BLOCKED', 0)}"
            )
    print(f"  ctx.call_count (shared)    : {ctx.call_count} / {POLICY.max_tool_calls}")

    audit(
        "claude",
        "all_hooks_demo",
        "ALLOWED",
        f"factories_registered={len(factories)} events_fired={len(by_phase.keys() & factories.keys())}",
        policy=POLICY.name,
    )


if __name__ == "__main__":
    import _shared  # noqa: F401

    asyncio.run(main())
