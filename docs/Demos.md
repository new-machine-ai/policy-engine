# Demos & Examples

`policy_engine` ships three demo folders. They all enforce the same
governance through `BaseKernel.evaluate` and append to the same
`policy_engine.AUDIT` list, so output across them looks identical —
the difference is which SDK surface the demo wires the kernel into,
and which historical layout the file lives in.

> Companion pages: [[Core-Concepts]] for kernel mechanics;
> [[Seam-Taxonomy]] for where each adapter calls `evaluate`;
> [[Adapter-API-Shape]] for `governed_<noun>` vs `as_<noun>`.

If you only run one thing, run the consolidated hello suite — it's
the canonical home and exercises every adapter that has a live
hello-world counterpart:

```sh
cd policy_engine_hello_world_multi_real_consolidated
python run_all.py --profile hello
```

## Quick start

The five most useful invocations live in the consolidated folder:

```sh
cd policy_engine_hello_world_multi_real_consolidated
python run_all.py --list                    # every demo + profile
python run_all.py --profile hello           # 5 live SDK hello-worlds
python run_all.py --profile showcase        # 8 deep-dive demos
python run_all.py --only policy_deep_dive   # the kernel walkthrough
python policy_engine_deep_dive.py           # standalone, no runner
```

Add `--strict` to make the runner fail loudly on missing optional
deps or credentials instead of printing `[skip]`.

## `policy_engine_hello_world_multi_real_consolidated/` — canonical

The authoritative home. New demos belong here. Its `run_all.py`
discovers every entry in a single `DEMOS` list and splits them
across two `--profile` values (`hello` and `showcase`).

The unified rulebook every demo enforces is defined once in
`_shared.py`:

```python
POLICY = GovernancePolicy(
    name="lite-policy",
    blocked_patterns=[
        "DROP TABLE",
        "rm -rf",
        "ignore previous instructions",
        "reveal system prompt",
        "<system>",
    ],
    max_tool_calls=10,
    blocked_tools=["shell_exec", "network_request", "file_write"],
)
```

Some demos use a smaller per-framework override (e.g.
`LANGCHAIN_POLICY`, `ANTHROPIC_POLICY`) for the live hello-world
smoke run.

### Hello profile — 5 live demos

| Key | Module | Purpose | Seam | Credentials |
|---|---|---|---|---|
| `langchain` | `langchain_agent.py` | LangChain hello-world | `LangChainKernel.as_middleware()` in `create_agent(...)` | `OPENAI_API_KEY` |
| `openai_agents` | `openai_agent.py` | OpenAI Agents SDK hello-world | `OpenAIAgentsKernel.governed_runner(Runner)` | `OPENAI_API_KEY` |
| `maf` | `microsoft_agent.py` | Microsoft Agent Framework hello-world | `MAFKernel.as_middleware()` in `Agent(...)` | `OPENAI_API_KEY` |
| `anthropic` | `anthropic_agent.py` | Anthropic SDK hello-world | `AnthropicKernel.governed_client(client)` | `ANTHROPIC_API_KEY` |
| `claude_hello` | `claude_agent_sdk_agent.py` | Claude Agent SDK hello-world | `ClaudeSDKKernel.governed_options(opts)` | `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, or `~/.claude/.credentials.json` |

### Showcase profile — 8 deep-dive demos

| Key | Module | Purpose | Seam | Credentials |
|---|---|---|---|---|
| `governance` | `governance_showcase.py` | Multi-stage governance — policy, trust, MCP, lifecycle | Direct `BaseKernel.evaluate()`, no SDK | None |
| `agent_os` | `agent_os_governed.py` | Agent-OS backend bridge | `AgentOSKernel` (subclass over `PolicyInterceptor`) | None |
| `openai_assist` | `openai_assistants_governed.py` | OpenAI Assistants method-level proxy | `OpenAIKernel.wrap(assistant, client)` | `OPENAI_API_KEY` |
| `crewai` | `crewai_governed.py` | CrewAI before/after LLM hooks | `@before_llm_call` / `@after_llm_call` over `CrewAIKernel` | `OPENAI_API_KEY` |
| `pydantic_ai` | `pydantic_ai_governed.py` | PydanticAI agent wrap | `PydanticAIKernel.wrap(agent)` | `OPENAI_API_KEY` |
| `claude` | `claude_governed.py` | Claude Agent SDK full agent loop | Shared `BaseKernel` across `UserPromptSubmit`, `PreToolUse`, `PostToolUse` | Anthropic creds (see `claude_hello` above) |
| `claude_all_hooks` | `claude_all_hooks.py` | Every Python-supported Claude hook factory wired | All ten hook factories registered in `ClaudeAgentOptions` | Anthropic creds |
| `policy_deep_dive` | `policy_engine_deep_dive.py` (+ `.ipynb`) | Kernel internals walkthrough — port of agent_os notebook 06 | Direct `BaseKernel.evaluate()`, no SDK | None (tutorial) |

The deep-dive entry is a Jupyter notebook
(`policy_engine_deep_dive.ipynb`) wrapped by a small `.py` shim that
parses the notebook as JSON and `exec`s each code cell. That's why
`run_all.py` can discover it without an `nbclient` dependency.

**Not in `DEMOS`:** `all_in_one.py` — a single-process orchestrator
that imports each of the five hello-world `main()`s and runs them
back-to-back. Useful for a one-shot live smoke; for routine use
prefer `run_all.py --profile hello`.

The Claude Agent SDK demos (`claude_governed.py`,
`claude_all_hooks.py`, `claude_agent_sdk_agent.py`) **cannot run
inside another Claude Code session** — the SDK rejects nested
sessions. Run them from a plain shell with `CLAUDECODE` unset.

## `policy_engine_demos/` — legacy showcase set

The original home for the showcase-style governed demos. Every
demo here has a counterpart in the consolidated folder; this folder
predates the consolidation. Its `run_all.py` uses an in-line
`_load_demos()` function rather than a `DEMOS` dataclass list.

Kept for historical reference; new work goes in the consolidated
folder.

| Module | Purpose | Seam | Consolidated counterpart |
|---|---|---|---|
| `agent_os_governed.py` | Agent-OS backend demo for the lightweight policy-engine facade | `AgentOSKernel` (`PolicyInterceptor` delegate) | `agent_os_governed.py` |
| `claude_all_hooks.py` | Register every Python-supported Claude hook factory | All ten Claude hook factories | `claude_all_hooks.py` |
| `claude_governed.py` | Claude Agent SDK full agent loop wired to policy_engine | Shared `BaseKernel` across multiple Claude hooks | `claude_governed.py` |
| `crewai_governed.py` | CrewAI `before/after_llm_call` decorators delegate to `CrewAIKernel` | `@before_llm_call` / `@after_llm_call` | `crewai_governed.py` |
| `google_adk_callbacks_governed.py` | Google ADK callback governance quickstart (deterministic, no live model) | `GoogleADKKernel.as_callbacks()` | **(none — only here)** |
| `governance_showcase.py` | Dependency-free governance showcase inspired by the .NET SDK demos | Direct `BaseKernel.evaluate()` | `governance_showcase.py` |
| `langchain_governed.py` | LangChain (LangGraph) `pre_model_hook` delegates to `LangChainKernel` | `LangChainKernel` middleware | `langchain_agent.py` |
| `maf_governed.py` | MAF middleware list from `policy_engine.adapters.maf` | `create_governance_middleware(...)` | `microsoft_agent.py` |
| `openai_agents_sdk_governed.py` | OpenAI Agents SDK — `OpenAIAgentsKernel` + wrapped Runner | `OpenAIAgentsKernel.governed_runner()` | `openai_agent.py` |
| `openai_assistants_governed.py` | OpenAI Assistants — `OpenAIKernel.wrap` from policy_engine | `OpenAIKernel.wrap(assistant, client)` | `openai_assistants_governed.py` |
| `pydantic_ai_governed.py` | PydanticAI — `PydanticAIKernel.wrap` from policy_engine | `PydanticAIKernel.wrap(agent)` | `pydantic_ai_governed.py` |

`google_adk_callbacks_governed.py` is the one demo unique to this
folder — added by the ADK adapter PR and not yet ported to the
consolidated folder.

## `policy_engine_hello_world_multi_real/` — preserved hello samples

The original live-hello-world set. Per `CLAUDE.md`, "Do not edit
unless explicitly asked." Every sample here has a near-identical
counterpart in the consolidated folder; the consolidated copies are
what `run_all.py --profile hello` exercises.

This folder's own `run_all.py` runs each sample as a separate
subprocess (one fresh Python process per sample), useful when you
want process isolation between framework imports.

| Module | Purpose | Seam | Consolidated counterpart |
|---|---|---|---|
| `langchain_agent.py` | LangChain hello-world | `LangChainKernel.as_middleware()` | `langchain_agent.py` |
| `openai_agent.py` | OpenAI Agents SDK hello-world | `OpenAIAgentsKernel.governed_runner()` | `openai_agent.py` |
| `microsoft_agent.py` | Microsoft Agent Framework hello-world | `MAFKernel.as_middleware()` | `microsoft_agent.py` |
| `anthropic_agent.py` | Anthropic SDK hello-world | `AnthropicKernel.governed_client()` | `anthropic_agent.py` |
| `google_adk_agent.py` | Live Google ADK hello-world | `GoogleADKKernel` | **(none — only here)** |
| `claude_agent_sdk_agent.py` | Claude Agent SDK hello-world | `ClaudeSDKKernel.governed_options()` | `claude_agent_sdk_agent.py` |
| `all_in_one.py` | Run all six samples in one Python process | Orchestrator | `all_in_one.py` (5-sample variant; no Google ADK) |

Like the legacy showcase folder, the Google ADK sample
(`google_adk_agent.py`) is unique to this folder and has not been
ported across.

## Audit trail shape

Every demo writes through `policy_engine.audit(...)` into the
process-wide `AUDIT` list. Each entry is a dict:

```python
{
    "ts": "2026-05-02T01:34:46+00:00",  # always present
    "framework": "claude",                # adapter / demo name
    "phase": "PreToolUse",                # seam-defined
    "status": "ALLOWED" | "BLOCKED",
    "detail": "...",                      # optional descriptive string
    "policy": "lite-policy",              # optional, from PolicyDecision
    "reason": "blocked_pattern:DROP TABLE",
    "tool_name": "shell_exec",
    "payload_hash": "01367c0db1fb...",   # SHA-256; raw payload never stored
}
```

Raw payloads are never persisted — only the hash. See
[[Core-Concepts]] for the full `PolicyDecision` shape and the
fixed evaluation order inside `BaseKernel.evaluate`.

## See also

- [[Core-Concepts]] — `BaseKernel.evaluate`, `GovernancePolicy`, audit
- [[Seam-Taxonomy]] — at-a-glance comparison of every adapter's seam
- [[Adapter-API-Shape]] — `governed_<noun>` vs `as_<noun>`
- [[Naming-Conventions]] — plain-English walkthrough of the verb/noun split
- [[MAF-Adapter]]
- [[OpenAI-Assistants-Adapter]]
- [[OpenAI-Agents-SDK-Adapter]]
- [[LangChain-Adapter]]
- [[CrewAI-Adapter]]
- [[PydanticAI-Adapter]]
- [[Claude-Agent-SDK-Adapter]]
- [[Anthropic-Adapter]]
- [[Google-ADK-Adapter]]
- [[Agent-OS-Backend-Adapter]]
