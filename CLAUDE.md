# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo layout

Example and package trees at the root:

- `policy-engine/` — the Python installable package (`pyproject.toml`, `src/policy_engine/`, `tests/`). Pure-stdlib core; per-framework adapters live in `src/policy_engine/adapters/` and lazily import their framework dep.
- `policy_engine_hello_world_multi_real_consolidated/` — canonical examples: compact live hello-world demos plus migrated showcase/deep-dive demos, with `run_all.py`, `_shared.py`, `governance_showcase.py`, and `claude_all_hooks.py`.
- `policy_engine_hello_world_multi_real/` — preserved original hello-world samples. Do not edit unless explicitly asked.

`docs/` holds wiki pages (`Home.md`, `Core-Concepts.md`, one page per adapter, `Seam-Taxonomy.md`, integration plans). Some pages still mention a vendored `agent-os/` tree from earlier commits — that folder has been removed from this checkout, so treat those references as historical until docs/ is reconciled.

The optional Agent-OS backend used to be vendored at `../agent-os/`; that tree has been removed. The `agent_os` adapter still works — it now installs via the `agent-os-kernel` PyPI package (extra: `policy-engine[agent-os]`) and the adapter still scans parent directories for a local checkout if one happens to exist.

## Common commands

Run from `policy-engine/`:

```
pip install -e ".[test]"               # install core + pytest
pip install -e ".[all]"                # core + every framework dep
pip install -e ".[agent-os]"           # optional Agent-OS backend (PyPI: agent-os-kernel)
pip install -e ".[langchain]"          # one framework's optional deps
python -m pytest tests/                # run unit tests (core only, no framework deps)
python -m pytest tests/test_policy.py::test_pre_execute_blocks_pattern -v   # one test
python -m pytest tests/test_claude_adapter.py -v                            # claude SDK hook factory tests
```

Run from `policy_engine_hello_world_multi_real_consolidated/`:

```
python run_all.py                              # all consolidated demos + audit summary
python run_all.py --list                       # list demo keys and profiles
python run_all.py --profile hello --strict     # compact live smoke suite
python run_all.py --profile showcase           # broader showcase/deep-dive suite
python run_all.py --only agent_os              # optional Agent-OS backend demo
python langchain_agent.py                      # a single compact demo
```

`run_all.py` swallows optional dependency/credential failures by default so they print `[skip]`. Use `--strict` when a live smoke run should fail loudly.

## How demos resolve `policy_engine` without an install

`policy_engine_hello_world_multi_real_consolidated/_shared.py` walks two candidate `sys.path` entries and uses whichever exists: `<repo_root>/policy-engine/src` (this checkout) and `<repo_root>/../packages/policy-engine/src` (parent monorepo). The first wins, so demos run straight from a fresh checkout without `pip install`. If you ever see `ModuleNotFoundError: policy_engine` from a demo, prefer `pip install -e ./policy-engine` over editing those candidates — the second path is intentionally there for a parent monorepo layout.

## Architecture

The package implements one shape of runtime governance — *prompt-pattern blocking + tool allow/deny + human approval + max-tool-call cap + audit trail* — and exposes it through seven framework-specific adapters plus an optional Agent-OS backend bridge. The core stays stdlib and small; everything interesting is in how each adapter plugs that core into a framework or backend extension point.

**Core (always loaded):**
- `policy.GovernancePolicy` — dataclass: `blocked_patterns`, `max_tool_calls`, `require_human_approval`, `allowed_tools`, `blocked_tools`. `matches_pattern(text)` is case-insensitive substring match.
- `policy.PolicyRequest` / `policy.PolicyDecision` — local structured request/decision types used by richer adapters.
- `policy.PolicyViolationError` — raised by adapters that gate via exception; carries `reason` + `pattern`.
- `context.ExecutionContext` — per-run state, currently just a `call_count`.
- `kernel.BaseKernel.evaluate(ctx, request) -> PolicyDecision` — **the single gate**. `pre_execute(ctx, payload) -> (allowed, reason)` remains as the compatibility wrapper.
- `audit.AUDIT` (list) + `audit(framework, phase, status, detail, decision=...)` — process-wide in-memory sink with UTC timestamps, policy/reason metadata, optional tool name, and payload hash. It must not store raw prompts.

**Adapters** (`src/policy_engine/adapters/<framework>.py`) fall into four patterns based on what extension point each framework offers:

| Pattern | Adapter | What it ships |
|---|---|---|
| Method-proxy wrap | `openai_assistants.OpenAIKernel.wrap(assistant, client)`, `pydantic_ai.PydanticAIKernel.wrap(agent)`, `openai_agents.OpenAIAgentsKernel.wrap_runner(Runner)` | A wrapper class whose entry-point methods call `pre_execute` before delegating. |
| Hook/middleware factory | `claude.make_*_hook(policy)` — ten factories, one per Python-supported SDK event (`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `Stop`, `SubagentStart`, `SubagentStop`, `PreCompact`, `PermissionRequest`, `Notification`); plus `maf.create_governance_middleware(...)` | A closure or list the framework's own hook system runs. No kernel object needed. All Claude factories accept optional shared `kernel`/`ctx` so they share `max_tool_calls` accounting. Seven are informational (audit-only: `PostToolUse`, `PostToolUseFailure`, `Stop`, `SubagentStart`, `SubagentStop`, `PreCompact`, `Notification`), two gate via `kernel.evaluate` (`UserPromptSubmit`, `PreToolUse`), one (`PermissionRequest`) emits the SDK's three-state allow/deny/ask. |
| Bare kernel | `langchain.LangChainKernel`, `crewai.CrewAIKernel` | Just `BaseKernel` re-exported under a `framework` name. The *demo* writes the framework hook (`pre_model_hook`, `@before_llm_call`) and calls `kernel.pre_execute` itself. |
| Backend bridge | `agent_os.AgentOSKernel`, `agent_os.to_agent_os_policy(...)` | A `BaseKernel`-compatible facade that lazily loads Agent-OS `PolicyInterceptor` (from a sibling `agent-os/` checkout if present, otherwise from the `agent-os-kernel` PyPI package) and preserves local `PolicyDecision` output. |

When adding a new adapter, pick the pattern that matches the target framework's native hook surface — don't force a wrap if the framework already has middleware. Mirror the existing adapter file's docstring style: it should explicitly name the seam (e.g., "Seam: `Agent(middleware=[...])`").

**Optional deps are encoded twice** — once in `pyproject.toml` extras, once as a lazy `import` inside the adapter module's functions/classes. Top-level `import policy_engine` must remain dep-free; do not add framework or Agent-OS imports at module scope in any adapter.

## Demo conventions

- Every demo is a `main()` (sync or async) that `run_all.py` discovers by name.
- Demos print step-by-step progress via `_shared.step(framework, msg)` and record decisions via `_shared.audit(...)` so the final unified audit trail in `run_all.py` shows the same `POLICY` enforced across all frameworks plus the optional Agent-OS backend demo.
- The shared `POLICY` is defined once in `_shared.py` (`blocked_patterns=["DROP TABLE", "rm -rf", "ignore previous instructions", "reveal system prompt", "<system>"]`, `max_tool_calls=10`, `blocked_tools=["shell_exec", "network_request", "file_write"]`). Compact hello demos may use the named hello policies from `_shared.py` when they need a smaller live-smoke policy.
- `claude_governed.py` and `claude_all_hooks.py` **cannot be run from inside another Claude Code session** — the Claude Agent SDK rejects nested sessions. Run them from a plain shell with `CLAUDECODE` unset.
- Several demos require `OPENAI_API_KEY` and self-skip with a printed message when it's missing.

## Non-goals (explicit)

Per `policy-engine/README.md`: the stdlib core does not implement drift detection, semaphores, YAML, audit persistence, an event bus, content-hash interceptors, or prompt-defense pre-screening. Keep those in the optional `agent_os` adapter or direct `agent-os-kernel` integration, not in the core kernel.
