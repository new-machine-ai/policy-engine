# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo layout

Three sibling trees at the root:

- `policy-engine/` — the installable package (`pyproject.toml`, `src/policy_engine/`, `tests/`). Pure-stdlib core; per-framework adapters live in `src/policy_engine/adapters/` and lazily import their framework dep.
- `policy_engine_demos/` — one quickstart per supported framework, plus `run_all.py` and `_shared.py`. Demos import the package (not vendored copies).
- `agent-os/` — vendored Agent-OS source used by the optional `policy_engine.adapters.agent_os` bridge. Do not import it from the core package path.

There is no git repo and no top-level README — each tree is self-describing.

## Common commands

Run from `policy-engine/`:

```
pip install -e ".[test]"               # install core + pytest
pip install -e ".[all]"                # core + every framework dep
pip install -e ../agent-os             # optional local Agent-OS backend
pip install -e ".[langchain]"          # one framework's optional deps
python -m pytest tests/                # run unit tests (core only, no framework deps)
python -m pytest tests/test_policy.py::test_pre_execute_blocks_pattern -v   # one test
```

Run from `policy_engine_demos/`:

```
python run_all.py                      # all 7 adapter demos + audit summary
python run_all.py --list               # list demo keys
python run_all.py --only agent_os      # optional Agent-OS backend demo
python run_all.py --only langchain crewai
python langchain_governed.py           # a single demo
```

`run_all.py` swallows `ImportError` so missing optional deps print `[skip]` rather than abort the run.

## Path gotcha when running demos from this checkout

`policy_engine_demos/_shared.py` injects `<repo_root>/packages/policy-engine/src` onto `sys.path`. That path **does not exist** in this checkout — the package lives at `policy-engine/src`, not under `packages/`. Two ways to make demos resolve `policy_engine`:

1. `pip install -e ./policy-engine` once — demos then import from site-packages and the broken sys.path entry is harmless.
2. `PYTHONPATH=$(pwd)/policy-engine/src python policy_engine_demos/run_all.py`.

Don't "fix" the `packages/...` path in `_shared.py` without checking — it likely targets a parent monorepo layout.

## Architecture

The package implements one shape of runtime governance — *prompt-pattern blocking + tool allow/deny + human approval + max-tool-call cap + audit trail* — and exposes it through seven framework-specific adapters plus an optional Agent-OS backend bridge. The core stays stdlib and small; everything interesting is in how each adapter plugs that core into a framework or backend extension point.

**Core (always loaded):**
- `policy.GovernancePolicy` — dataclass: `blocked_patterns`, `max_tool_calls`, `require_human_approval`, `allowed_tools`, `blocked_tools`. `matches_pattern(text)` is case-insensitive substring match.
- `policy.PolicyRequest` / `policy.PolicyDecision` — local structured request/decision types used by richer adapters.
- `policy.PolicyViolationError` — raised by adapters that gate via exception; carries `reason` + `pattern`.
- `context.ExecutionContext` — per-run state, currently just a `call_count`.
- `kernel.BaseKernel.evaluate(ctx, request) -> PolicyDecision` — **the single gate**. `pre_execute(ctx, payload) -> (allowed, reason)` remains as the compatibility wrapper.
- `audit.AUDIT` (list) + `audit(framework, phase, status, detail, decision=...)` — process-wide in-memory sink with UTC timestamps, policy/reason metadata, optional tool name, and payload hash. It must not store raw prompts.

**Adapters** (`src/policy_engine/adapters/<framework>.py`) fall into three patterns based on what extension point each framework offers:

| Pattern | Adapter | What it ships |
|---|---|---|
| Method-proxy wrap | `openai_assistants.OpenAIKernel.wrap(assistant, client)`, `pydantic_ai.PydanticAIKernel.wrap(agent)`, `openai_agents.OpenAIAgentsKernel.wrap_runner(Runner)` | A wrapper class whose entry-point methods call `pre_execute` before delegating. |
| Hook/middleware factory | `claude.make_*_hook(policy)` — ten factories, one per Python-supported SDK event (`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `Stop`, `SubagentStart`, `SubagentStop`, `PreCompact`, `PermissionRequest`, `Notification`); plus `maf.create_governance_middleware(...)` | A closure or list the framework's own hook system runs. No kernel object needed. All Claude factories accept optional shared `kernel`/`ctx` so they share `max_tool_calls` accounting. Six are informational (audit-only), two gate via `kernel.evaluate` (`UserPromptSubmit`, `PreToolUse`), one (`PermissionRequest`) emits the SDK's three-state allow/deny/ask. |
| Bare kernel | `langchain.LangChainKernel`, `crewai.CrewAIKernel` | Just `BaseKernel` re-exported under a `framework` name. The *demo* writes the framework hook (`pre_model_hook`, `@before_llm_call`) and calls `kernel.pre_execute` itself. |
| Backend bridge | `agent_os.AgentOSKernel`, `agent_os.to_agent_os_policy(...)` | A `BaseKernel`-compatible facade that lazily loads Agent-OS `PolicyInterceptor` and preserves local `PolicyDecision` output. |

When adding a new adapter, pick the pattern that matches the target framework's native hook surface — don't force a wrap if the framework already has middleware. Mirror the existing adapter file's docstring style: it should explicitly name the seam (e.g., "Seam: `Agent(middleware=[...])`").

**Optional deps are encoded twice** — once in `pyproject.toml` extras, once as a lazy `import` inside the adapter module's functions/classes. Top-level `import policy_engine` must remain dep-free; do not add framework or Agent-OS imports at module scope in any adapter.

## Demo conventions

- Every demo is a `main()` (sync or async) that `run_all.py` discovers by name.
- Demos print step-by-step progress via `_shared.step(framework, msg)` and record decisions via `_shared.audit(...)` so the final unified audit trail in `run_all.py` shows the same `POLICY` enforced across all seven frameworks and optional backend demos.
- The shared `POLICY` (`blocked_patterns=["DROP TABLE", "rm -rf"]`, `max_tool_calls=10`) is defined once in `_shared.py` — don't redefine it per demo unless the adapter needs extra fields (see `openai_agents_sdk_governed.py`, which adds `allowed_tools`/`blocked_tools`).
- `claude_governed.py` **cannot be run from inside another Claude Code session** — the Claude Agent SDK rejects nested sessions. Run it from a plain shell with `CLAUDECODE` unset.
- Several demos require `OPENAI_API_KEY` and self-skip with a printed message when it's missing.

## Non-goals (explicit)

Per `policy-engine/README.md`: the stdlib core does not implement drift detection, semaphores, YAML, audit persistence, an event bus, content-hash interceptors, or prompt-defense pre-screening. Keep those in the optional `agent_os` adapter or direct `agent-os` integration, not in the core kernel.
