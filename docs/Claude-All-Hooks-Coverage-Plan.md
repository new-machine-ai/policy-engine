# Plan: Fire all 10 Claude SDK hook events in one demo

## Context

`policy_engine_hello_world_multi_real_consolidated/claude_all_hooks.py` registers all ten Python-supported hook factories but, in a typical run, the SDK only emits four events:

```
gov[claude:all_hooks_demo] ALLOWED - factories_registered=10 events_fired=4
```

The four that fire on any short read-only query are `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, and `Stop`. The other six are dormant because they depend on specific SDK behaviour:

| Hook | Why it didn't fire |
|---|---|
| `PostToolUseFailure` | No tool actually raised |
| `SubagentStart` / `SubagentStop` | The agent never invoked the `Task` tool |
| `PreCompact` | Context window stayed below the compaction threshold and `/compact` was never sent |
| `PermissionRequest` | Every tool the agent wanted was already on `allowed_tools`, so no permission dialog was needed |
| `Notification` | No `permission_prompt`, `idle_prompt`, `auth_success`, or `elicitation_dialog` event was emitted |

This plan upgrades `claude_all_hooks.py` so the demo deliberately provokes each dormant event in its own phase. The end-state is a one-shot run that prints `events_fired=10`.

**Outcome:** every factory the adapter ships gets at least one row in the unified audit trail per run, proving the wiring end-to-end on a single Claude session — not just in the synthetic unit tests.

## Provocation strategy per dormant hook

Each phase runs a separate `query()` (so a failure in one phase doesn't poison later ones) with a slightly-relaxed `ClaudeAgentOptions` tailored to the hook being exercised. The same shared `BaseKernel` + `ExecutionContext` thread through every phase so `max_tool_calls` accounting still matches `claude_governed.py`'s contract.

### Phase A — baseline (fires 4 hooks)

`UserPromptSubmit` + `PreToolUse` + `PostToolUse` + `Stop`. This is what the current demo already does.

```python
options_a = ClaudeAgentOptions(
    allowed_tools=["Read", "Glob", "Grep"],
    setting_sources=[],
    max_turns=2,
    permission_mode="default",
    system_prompt="Answer in one short sentence using Glob/Read/Grep.",
    hooks=hooks_dict,
)
await _drain(query(
    prompt="List the .py files in this directory.",
    options=options_a,
))
```

### Phase B — fire `PostToolUseFailure` (1 more → 5)

Trigger a tool that's guaranteed to error. `Read` against a non-existent absolute path is the safest bet — it doesn't need any extra tool on the allowlist:

```python
options_b = ClaudeAgentOptions(
    allowed_tools=["Read"],
    setting_sources=[],
    max_turns=2,
    permission_mode="default",
    system_prompt=(
        "Read the absolute path /tmp/policy-engine-demo-DOES-NOT-EXIST.txt "
        "and report what happened. Do not retry."
    ),
    hooks=hooks_dict,
)
await _drain(query(
    prompt="Read that file now and tell me the error.",
    options=options_b,
))
```

The `Read` tool surfaces a `FileNotFoundError` to the SDK, which fires `PostToolUseFailure`. The hook factory records a `BLOCKED` row tagged with `tool=Read` and `reason=...` (truncated to 200 chars by the factory).

### Phase C — fire `SubagentStart` + `SubagentStop` (2 more → 7)

Add `Task` to `allowed_tools` and explicitly ask Claude to delegate. The Task tool spawns a subagent; the SDK fires `SubagentStart` when it spawns and `SubagentStop` when it returns:

```python
options_c = ClaudeAgentOptions(
    allowed_tools=["Read", "Glob", "Grep", "Task"],
    setting_sources=[],
    max_turns=4,
    permission_mode="default",
    system_prompt=(
        "Always delegate research questions to a subagent via the Task tool. "
        "Do not answer directly."
    ),
    hooks=hooks_dict,
)
await _drain(query(
    prompt=(
        "Use the Task tool to spawn a research subagent that counts the "
        "Python files in policy_engine_hello_world_multi_real_consolidated/ and reports the number."
    ),
    options=options_c,
))
```

Caveat: model behaviour isn't deterministic — Claude may sometimes ignore the system prompt and answer directly. A backup wording that tends to be more reliable: `"Spawn a research subagent (Task tool) — do not perform the count yourself."`

### Phase D — fire `PreCompact` (1 more → 8)

The cheapest way is the SDK's manual-compaction path documented in *How the agent loop works*: send `/compact` as a prompt string. This requires a session that has at least some history to summarize, so it has to come after Phase A (which leaves transcripts on disk):

```python
# Manual compaction needs an existing session to compact. Reuse Phase A's
# session by capturing its session_id, then resume + send /compact.
await _drain(query(
    prompt="/compact",
    options=ClaudeAgentOptions(
        allowed_tools=["Read", "Glob", "Grep"],
        setting_sources=[],
        max_turns=1,
        permission_mode="default",
        resume=phase_a_session_id,  # captured during Phase A's _drain
        hooks=hooks_dict,
    ),
))
```

This requires a small refactor of `_drain` to also capture and return `session_id` (mirrors `claude_governed.py`'s pattern). The compactor reads the prior transcript, fires `PreCompact` with `trigger="manual"`, and the factory records a row with `detail="trigger=manual"`.

Caveat: if the SDK version the user has installed treats `/compact` as a literal user message instead of a slash command (older versions), this phase will fire `UserPromptSubmit` but not `PreCompact`. Document the SDK version requirement (≥ the version that ships slash-command-as-input).

### Phase E — fire `PermissionRequest` + `Notification` (2 more → 10)

Use a tool that **isn't** in `allowed_tools` while `permission_mode="default"` and no `canUseTool` callback is supplied. The SDK then has to fall back to its permission dialog, which fires `PermissionRequest` (so the hook gets a chance to allow/deny/ask) and emits a `Notification` of subtype `permission_prompt`:

```python
options_e = ClaudeAgentOptions(
    # Note: NO Bash here — but the prompt asks for it.
    allowed_tools=["Read", "Glob"],
    setting_sources=[],
    max_turns=2,
    permission_mode="default",
    system_prompt=(
        "When asked to run a shell command, use the Bash tool. "
        "Do not substitute a different tool."
    ),
    hooks=hooks_dict,
)
await _drain(query(
    prompt="Use the Bash tool to print 'hello' (the command: echo hello).",
    options=options_e,
))
```

The factory's `make_permission_request_hook` will evaluate the request through `kernel.evaluate(PolicyRequest(payload=..., tool_name="Bash", phase="PermissionRequest"))`. With the shared `_shared.POLICY` (where `Bash` isn't in `blocked_tools`), the policy allows; the hook returns `permissionDecision: "allow"`. That gives a clean `ALLOWED` row for `PermissionRequest`.

The `Notification` fires regardless of how the hook decides — it's the SDK signalling that a permission dialog *would* appear. The factory records a row with `detail="type=permission_prompt msg=..."`.

Caveat: if the user wants to see a `BLOCKED` `PermissionRequest` instead, swap the prompt for one whose tool is in `POLICY.blocked_tools` (e.g. `shell_exec`). But that tool isn't a real Claude SDK tool, so the agent won't actually call it. The `Bash`-allow path is the only one that produces a clean fire-and-record cycle.

### Phase F — audit summary (unchanged from current demo)

Same per-hook breakdown as today, except now the expected output is:

```
  Hook factories registered  : 10 / 10
  Total Claude audit events  : ≥10
  Hook events that fired     :
    UserPromptSubmit         ALLOWED=N BLOCKED=0
    PreToolUse               ALLOWED=N BLOCKED=0
    PostToolUse              ALLOWED=N BLOCKED=0
    PostToolUseFailure       ALLOWED=0 BLOCKED=1
    Stop                     ALLOWED=N BLOCKED=0
    SubagentStart            ALLOWED=1 BLOCKED=0
    SubagentStop             ALLOWED=1 BLOCKED=0
    PreCompact               ALLOWED=1 BLOCKED=0
    PermissionRequest        ALLOWED=1 BLOCKED=0
    Notification             ALLOWED=1 BLOCKED=0
```

A green run is `events_fired=10` printed in the closing audit row.

## Implementation outline

### Modify — `policy_engine_hello_world_multi_real_consolidated/claude_all_hooks.py`

1. Update `_drain` to also capture and return `session_id` from the `ResultMessage` (Phase D needs it). Keep the existing per-message `step()` output.

2. Replace the single `query()` call with five sequential phases (A → B → C → D → E). Each phase builds its own `ClaudeAgentOptions` so the relevant tool allowlist / system prompt is scoped to the goal of that phase. The same `hooks_dict` (built once at the top) is reused across every phase so audit rows accumulate against the shared kernel.

3. Capture each phase's `session_id` and `subtype` in a small list of `(phase_label, summary)` tuples for the closing summary.

4. Replace the closing summary block with the table-shaped output above, plus a "Phases run" section showing which phases actually completed (some may be skipped on older SDK versions).

5. Tighten the docstring: "Wires every Python-supported hook factory and runs five sequenced phases, each designed to provoke a specific event so all ten factories produce at least one audit row per run."

The estimated diff is ~120 net new lines (the file goes from ~190 → ~310). No new imports beyond what's already in the file.

### No changes — adapter / tests / `_shared.POLICY`

The seven new factories already work in isolation (16 unit tests in `tests/test_claude_adapter.py` prove it). This plan only changes which SDK behaviour the demo provokes; it does not change what the factories do or the policy they enforce.

### Optional — `policy_engine_hello_world_multi_real_consolidated/run_all.py`

No changes. The demo stays registered as `claude_all_hooks`; only the per-phase output gets richer.

### Optional — `docs/Claude-Agent-SDK-Full-Demo.md`

Cross-link from §3.5 to this plan once it's implemented, so a reader who wonders "where do the seven new factories actually fire?" gets pointed at a concrete demo phase.

## Sample code — full `main()` outline

The fragment below stitches the phases together. It elides the imports, the kernel/ctx build, the auth-check, and the closing summary (those are unchanged from today). Each `_drain` call returns a summary dict that includes `session_id`.

```python
async def main() -> None:
    if os.environ.get("CLAUDECODE"):
        print("[skip] cannot run inside a Claude Code session")
        return

    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, query
    from policy_engine.adapters.claude import (
        make_user_prompt_hook, make_pre_tool_use_hook, make_post_tool_use_hook,
        make_post_tool_failure_hook, make_stop_hook,
        make_subagent_start_hook, make_subagent_stop_hook,
        make_pre_compact_hook, make_permission_request_hook,
        make_notification_hook,
    )
    from policy_engine.kernel import BaseKernel

    if not _claude_auth_present():
        print("[skip] needs Claude auth"); return

    kernel = BaseKernel(POLICY)
    ctx = kernel.create_context("claude_all_hooks")

    factories = {
        "UserPromptSubmit":  make_user_prompt_hook,
        "PreToolUse":        make_pre_tool_use_hook,
        "PostToolUse":       make_post_tool_use_hook,
        "PostToolUseFailure": make_post_tool_failure_hook,
        "Stop":              make_stop_hook,
        "SubagentStart":     make_subagent_start_hook,
        "SubagentStop":      make_subagent_stop_hook,
        "PreCompact":        make_pre_compact_hook,
        "PermissionRequest": make_permission_request_hook,
        "Notification":      make_notification_hook,
    }
    hooks_dict = {
        event: [HookMatcher(hooks=[factory(POLICY, kernel=kernel, ctx=ctx)])]
        for event, factory in factories.items()
    }

    def _opts(allowed, *, system, max_turns=2, resume=None):
        kwargs = dict(
            allowed_tools=allowed,
            setting_sources=[],
            max_turns=max_turns,
            permission_mode="default",
            system_prompt=system,
            hooks=hooks_dict,
        )
        if resume:
            kwargs["resume"] = resume
        return ClaudeAgentOptions(**kwargs)

    phase_results: list[tuple[str, dict]] = []

    # Phase A — baseline
    step("claude_all_hooks", "Phase A — baseline read-only query.")
    a = await _drain(query(
        prompt="List the .py files in this directory.",
        options=_opts(["Read", "Glob", "Grep"],
                      system="Answer in one short sentence using Glob/Read/Grep."),
    ))
    phase_results.append(("A", a))

    # Phase B — PostToolUseFailure
    step("claude_all_hooks", "Phase B — provoke PostToolUseFailure.")
    b = await _drain(query(
        prompt="Read that file now and tell me the error.",
        options=_opts(["Read"], system=(
            "Read the absolute path /tmp/policy-engine-demo-DOES-NOT-EXIST.txt "
            "and report what happened. Do not retry."
        )),
    ))
    phase_results.append(("B", b))

    # Phase C — Subagent start/stop
    step("claude_all_hooks", "Phase C — provoke SubagentStart + SubagentStop.")
    c = await _drain(query(
        prompt=(
            "Use the Task tool to spawn a research subagent that counts the "
            "Python files in policy_engine_hello_world_multi_real_consolidated/ and reports the number."
        ),
        options=_opts(["Read", "Glob", "Grep", "Task"], max_turns=4, system=(
            "Always delegate research questions to a subagent via the Task tool. "
            "Do not answer directly."
        )),
    ))
    phase_results.append(("C", c))

    # Phase D — PreCompact via /compact slash command (resumes Phase A's session)
    if a.get("session_id"):
        step("claude_all_hooks", "Phase D — provoke PreCompact via /compact.")
        d = await _drain(query(
            prompt="/compact",
            options=_opts(["Read", "Glob", "Grep"], max_turns=1,
                          resume=a["session_id"],
                          system="(compaction)"),
        ))
        phase_results.append(("D", d))

    # Phase E — PermissionRequest + Notification:permission_prompt
    step("claude_all_hooks", "Phase E — provoke PermissionRequest + Notification.")
    e = await _drain(query(
        prompt="Use the Bash tool to print 'hello' (the command: echo hello).",
        options=_opts(["Read", "Glob"], system=(
            "When asked to run a shell command, use the Bash tool. "
            "Do not substitute a different tool."
        )),
    ))
    phase_results.append(("E", e))

    # Closing summary — identical to today's, except with per-phase rollup
    _print_summary(phase_results, factories)
```

`_print_summary` reuses the existing per-phase audit aggregation logic; it just iterates over the new `phase_results` list to also print which `subtype` each phase ended in (some phases legitimately end in `error_during_execution` — e.g., Phase B if the agent retried and burnt the turn budget — and that's still a successful provocation as long as `PostToolUseFailure` fired).

## Verification

1. **Skip path (no SDK or no auth):** identical to today's behaviour.
2. **Full run, fresh session:**
   ```
   unset CLAUDECODE
   python policy_engine_hello_world_multi_real_consolidated/run_all.py --only claude_all_hooks
   ```
   Expected: `events_fired=10` printed in the closing line.
3. **Per-event spot-check:** every factory in `factories` should appear with at least one ALLOWED or BLOCKED count. If a phase didn't fire its target hook (model behaviour drift), the table makes that visible immediately.
4. **Cross-check with `claude_governed.py`:** running both demos in the unified suite should still show the existing `claude_governed`'s six-phase audit rollup unchanged.

## Caveats and known fragility

- **Model behaviour isn't deterministic.** Phase C (Task) and Phase E (Bash request without Bash on allowlist) rely on the agent obeying the system prompt. On rare runs the agent will substitute a different tool or refuse. The audit table makes this visible, but `events_fired` could land at 8 or 9 instead of 10.
- **`/compact` is documented but version-sensitive.** If Phase D doesn't fire `PreCompact` on the user's installed SDK, fall back to filling the context window. Easiest filler: ask the agent to read the largest file under `docs/` ten times in a row. Slower, but version-agnostic.
- **`Notification.auth_success` may already fire on first session init** depending on SDK version. If so, Phase A's first run also fires `Notification` and Phase E becomes redundant for that hook. The `events_fired=10` invariant still holds.
- **`PermissionRequest` doesn't always coincide with `Notification.permission_prompt`.** Some SDK versions emit one but not the other. Phase E targets both via the same triggering condition; if only one fires, the demo still gets a `PermissionRequest` row, and `Notification` would need a second tactic (e.g., a prompt that lets the agent call `AskUserQuestion`, which fires `Notification.elicitation_dialog`). Add a Phase E-bis only if Phase E proves insufficient in practice.
- **Audit volume.** Five phases means significantly more SDK API calls and more total cost than the current single-query demo. Expect ~$0.05-$0.20 per full run depending on the model. Cap with `max_budget_usd=1.00` if running in CI.

## See also

- [[Claude-Agent-SDK-Full-Demo]] — `claude_governed.py` architecture and the six-phase agent-loop demo.
- [[Claude-Agent-SDK-Adapter]] — full reference for `ClaudeAgentOptions` fields (`permission_mode`, `setting_sources`, `resume`, `fork_session`).
