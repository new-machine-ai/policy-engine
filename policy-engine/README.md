# policy-engine

A bare-bones runtime policy engine for popular agent frameworks. Pure stdlib
core; framework deps are optional and lazily imported per adapter. The optional
Agent-OS adapter can use the vendored `../agent-os` source tree for richer
governance without changing the small core API.

## Scope

This package re-implements **only** the runtime surface needed to gate prompts
and tool calls across popular agent frameworks and SDKs:

| Framework | Adapter import |
|---|---|
| Microsoft Agent Framework (MAF) | `policy_engine.adapters.maf` |
| OpenAI Assistants | `policy_engine.adapters.openai_assistants` |
| OpenAI Agents SDK | `policy_engine.adapters.openai_agents` |
| LangChain (LangGraph) | `policy_engine.adapters.langchain` |
| CrewAI | `policy_engine.adapters.crewai` |
| PydanticAI | `policy_engine.adapters.pydantic_ai` |
| Claude Agent SDK | `policy_engine.adapters.claude` |
| Anthropic SDK | `policy_engine.adapters.anthropic` |
| Google ADK | `policy_engine.adapters.google_adk` |
| Agent-OS backend | `policy_engine.adapters.agent_os` |

## Public API

```python
from policy_engine import (
    GovernancePolicy,
    PolicyRequest,
    PolicyDecision,
    PolicyViolationError,
    ExecutionContext,
    BaseKernel,
    AUDIT,
    audit,
)

policy = GovernancePolicy(
    name="my-policy",
    blocked_patterns=["DROP TABLE", "rm -rf"],
    max_tool_calls=10,
    blocked_tools=["shell_exec"],
)

kernel = BaseKernel(policy)
ctx = kernel.create_context("run-1")
decision = kernel.evaluate(
    ctx,
    PolicyRequest(payload="Say hello.", tool_name="search"),
)
assert isinstance(decision, PolicyDecision)

# Backward-compatible tuple API still works.
allowed, reason = kernel.pre_execute(ctx, "Say hello.")
```

Adapters are imported separately so a missing optional framework dep does not
break `import policy_engine`:

```python
from policy_engine.adapters.langchain import LangChainKernel
from policy_engine.adapters.maf import create_governance_middleware
```

Agent-OS is also imported separately. From this checkout, either install the
vendored source once or let the adapter discover `../agent-os/src`:

```python
from policy_engine import GovernancePolicy, PolicyRequest
from policy_engine.adapters.agent_os import AgentOSKernel

kernel = AgentOSKernel(GovernancePolicy(blocked_patterns=["DROP TABLE"]))
ctx = kernel.create_context("run-1")
decision = kernel.evaluate(ctx, PolicyRequest(payload="DROP TABLE users"))
assert not decision.allowed
```

```
pip install -e ./agent-os
```

## Non-goals

The stdlib core still does not implement drift detection, semaphores, YAML,
audit persistence, an event bus, content-hash interceptors, or prompt-defense
pre-screening. Use the optional `agent_os` adapter or direct `agent-os`
integration when you want to explore those heavier capabilities.

## Demos

Parallel demos live in `policy_engine_demos/`. Run them all from the repo root:

```
python policy_engine_demos/run_all.py
```

Google ADK has two examples in this checkout:
`policy_engine_demos/google_adk_callbacks_governed.py` is deterministic and
does not require a live model; `policy_engine_hello_world_multi_real/google_adk_agent.py`
uses a live ADK `LlmAgent`/`InMemoryRunner` and requires Google credentials.
