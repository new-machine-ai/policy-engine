# Hello-World Snippets — minimal policy-engine wire-ups

The smallest possible "build a policy, plug it into the framework, run
the agent" snippet for each supported SDK. Every snippet is one
`GovernancePolicy(...)`, one kernel call to produce the framework's
native shape, and one normal agent run.

> Companion pages: [[Adapter-API-Shape]] for *why* each kernel returns
> a different noun; [[Seam-Taxonomy]] for *where* in the call stack
> the policy is evaluated; [[Demos]] for the full runnable demos these
> snippets are distilled from.

All five snippets below share the same `GovernancePolicy(blocked_patterns=["DROP TABLE"])`,
the same `BaseKernel.evaluate` gate, and the same `policy_engine.AUDIT`
sink. Only the seam — middleware vs. options vs. runner vs. plugin —
changes between SDKs.

## LangChain 1.x

Seam: `create_agent(..., middleware=[...])`. Requires `OPENAI_API_KEY`.

```python
# Framework: LangChain 1.x (langchain)
from langchain.agents import create_agent
from policy_engine import GovernancePolicy
from policy_engine.adapters.langchain import LangChainKernel

policy = GovernancePolicy(blocked_patterns=["DROP TABLE"])
middleware = LangChainKernel(policy).as_middleware()

agent = create_agent(
    model="openai:gpt-4o-mini",
    tools=[calculator, web_search],
    middleware=[middleware],
)
result = agent.invoke({"messages": [{"role": "user", "content": "hello"}]})
print(result["messages"][-1].content)
```

## OpenAI Agents SDK

Seam: `OpenAIAgentsKernel.governed_runner(Runner)` — drop-in `Runner`
class replacement. Requires `OPENAI_API_KEY`.

```python
# Framework: OpenAI Agents SDK (openai-agents)
from agents import Agent, Runner
from policy_engine import GovernancePolicy
from policy_engine.adapters.openai_agents import OpenAIAgentsKernel

policy = GovernancePolicy(blocked_patterns=["DROP TABLE"])
runner = OpenAIAgentsKernel(policy).governed_runner(Runner)

agent = Agent(
    name="assistant",
    model="gpt-4o-mini",
    instructions="Be friendly.",
)
result = await runner.run(agent, "hello")
print(result.final_output)
```

## Microsoft Agent Framework

Seam: `Agent(middleware=[...])`. Requires `OPENAI_API_KEY` (for
`OpenAIChatClient`).

```python
# Framework: Microsoft Agent Framework (agent-framework)
from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
from policy_engine import GovernancePolicy
from policy_engine.adapters.maf import MAFKernel

policy = GovernancePolicy(blocked_patterns=["DROP TABLE"])
middleware = MAFKernel(policy).as_middleware(agent_id="hello-maf")

async with Agent(
    client=OpenAIChatClient(model="gpt-4o-mini"),
    name="hello-maf",
    middleware=middleware,
) as agent:
    response = await agent.run("hello")
    print(response.text)
```

## Claude Agent SDK

Seam: `ClaudeAgentOptions.hooks` — `governed_options` returns a copy
with the policy hooks pre-attached. Requires `ANTHROPIC_API_KEY` or a
`CLAUDE_CODE_OAUTH_TOKEN`.

> ⚠️ Cannot run inside another Claude Code session — the SDK rejects
> nested sessions. Run from a plain shell with `CLAUDECODE` unset.

```python
# Framework: Claude Agent SDK (claude-agent-sdk)
from claude_agent_sdk import ClaudeAgentOptions, query
from policy_engine import GovernancePolicy
from policy_engine.adapters.claude import ClaudeSDKKernel

policy = GovernancePolicy(blocked_patterns=["DROP TABLE"])
options = ClaudeSDKKernel(policy).governed_options(
    ClaudeAgentOptions(system_prompt="Be friendly.")
)
async for msg in query(prompt="hello", options=options):
    print(msg)
```

## Google ADK

Seam: `InMemoryRunner(plugins=[...])`. Requires `GOOGLE_API_KEY` (or
the Vertex AI env triple `GOOGLE_GENAI_USE_VERTEXAI`,
`GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`).

```python
# Framework: Google ADK (google-adk)
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from policy_engine import GovernancePolicy
from policy_engine.adapters.google_adk import GoogleADKKernel

policy = GovernancePolicy(blocked_patterns=["DROP TABLE"])
plugin = GoogleADKKernel(policy).as_plugin()

agent = LlmAgent(
    name="hello",
    model="gemini-2.5-flash",
    instruction="Be friendly.",
)
runner = InMemoryRunner(agent=agent, app_name="hello", plugins=[plugin])
events = await runner.run_debug("hello", quiet=True)
await runner.close()
print(events[-1].content.parts[0].text)
```

## What's the same across all five

- **One `GovernancePolicy`.** The dataclass is framework-agnostic;
  every adapter consumes it unchanged.
- **One `BaseKernel.evaluate` gate.** Every kernel subclasses
  `BaseKernel`, so the check order is identical regardless of SDK
  ([[Core-Concepts]]).
- **One audit trail.** Every adapter writes to `policy_engine.AUDIT`
  with consistent `framework` / `phase` / `status` columns. Inspect
  with `from policy_engine import AUDIT`.
- **One blocked behaviour.** Each snippet's policy says "reject any
  text containing `DROP TABLE`" (case-insensitive substring). Pass
  `"please DROP TABLE users"` instead of `"hello"` and the snippet
  short-circuits before the model is called.

## What varies — and why

The kernel method's noun (`middleware`, `runner`, `options`, `plugin`)
is dictated by what the host SDK's seam actually accepts. The verb
(`as_` vs. `governed_`) reflects whether you hand the kernel a seed
object to transform or ask it to fabricate a fresh handle from policy
state alone. See [[Adapter-API-Shape]] for the full reasoning.

| SDK | Wire-up call | Returns |
|---|---|---|
| LangChain 1.x | `LangChainKernel(p).as_middleware()` | `AgentMiddleware` instance |
| OpenAI Agents SDK | `OpenAIAgentsKernel(p).governed_runner(Runner)` | `Runner`-shaped class |
| Microsoft Agent Framework | `MAFKernel(p).as_middleware(agent_id=...)` | `list[middleware]` |
| Claude Agent SDK | `ClaudeSDKKernel(p).governed_options(opts)` | `ClaudeAgentOptions` copy |
| Google ADK | `GoogleADKKernel(p).as_plugin()` | ADK `BasePlugin` instance |
