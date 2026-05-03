# Naming Conventions — `governed_<noun>` vs `as_<noun>`

Companion to [[Adapter-API-Shape]]. This page is the plain-English walkthrough; that one is the formal reference.

## The question

Each kernel exposes one or two methods you call to turn governance on. Should they all share the same name?

## The rule a uniform name would need

> A method should be called `governed_<noun>` only if it **takes an SDK object as input and returns a governed-but-drop-in replacement.**

"Takes a seed" is the load-bearing part. With nothing to transform, there's no "governed copy of a seed" to return.

## How each method scores

| Method | Takes an SDK object? | Returns a transformed copy? | Fits `governed_<noun>`? |
|---|---|---|---|
| `AnthropicKernel.governed_client(client)` | yes — an `Anthropic()` client | yes | **Fits** |
| `ClaudeSDKKernel.governed_options(opts)` | yes — `ClaudeAgentOptions` | yes | **Fits** |
| `OpenAIAgentsKernel.governed_runner(Runner)` | yes — the `Runner` class | yes | **Fits** |
| `LangChainKernel.as_middleware()` | **no** | constructs fresh | **Doesn't fit** |
| `MAFKernel.as_middleware(agent_id=...)` | **no** | constructs fresh | **Doesn't fit** |

The first three transform something the caller already has. The last two **manufacture** a middleware out of the kernel's policy.

## Why `as_<noun>` is the right verb for the manufacturing methods

`as_<noun>` is the standard Python idiom for "give me this thing as a `<type>`":

- `dataclasses.asdict(obj)` — represent a dataclass as a dict
- `pathlib.Path.as_posix()` — represent a path as a posix string
- `concurrent.futures.as_completed(...)` — view futures as a stream of completions

`LangChainKernel(p).as_middleware()` reads exactly the same way: "represent this kernel as a piece of LangChain middleware." The kernel **is** the policy; calling `.as_middleware()` produces the framework's expected handle.

Renaming it to `governed_middleware()` would also be redundant — you called it on a kernel, of course the result is governed. The "governed" prefix is informative on `governed_client` because it warns you *the client you handed in is no longer the only one in play*. There's nothing equivalent to warn about when no input was handed in.

## Two patterns, not one forced one

| Demo | Wire-up | Pattern |
|---|---|---|
| Anthropic | `AnthropicKernel(p).governed_client(client)` | `governed_<noun>(seed)` |
| Claude Agent SDK | `ClaudeSDKKernel(p).governed_options(opts)` | `governed_<noun>(seed)` |
| OpenAI Agents | `OpenAIAgentsKernel(p).governed_runner(Runner)` | `governed_<noun>(seed)` |
| LangChain | `LangChainKernel(p).as_middleware()` | `as_<noun>()` |
| MAF | `MAFKernel(p).as_middleware(agent_id=...)` | `as_<noun>(...)` |

- **`governed_<noun>(seed)`** — "transform this SDK object into a governed copy that drops into the same call site."
- **`as_<noun>(...)`** — "construct the governance handle the framework's middleware list expects."

Two verbs that mean two different things is more honest than five entries that all read alike but behave differently underneath.

## Wire-up examples

Minimal, runnable shape for each framework. Each block is a hello-world stripped to the policy-engine wire-up.

### Claude Agent SDK

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

### OpenAI Agents SDK

```python
# Framework: OpenAI Agents SDK (openai-agents)
from agents import Agent, Runner
from policy_engine import GovernancePolicy
from policy_engine.adapters.openai_agents import OpenAIAgentsKernel

policy = GovernancePolicy(blocked_patterns=["DROP TABLE"])
runner = OpenAIAgentsKernel(policy).governed_runner(Runner)
agent = Agent(name="assistant", model="gpt-4o-mini", instructions="Be friendly.")
result = await runner.run(agent, "hello")
print(result.final_output)
```

### LangChain

```python
# Framework: LangChain 1.x (langchain)
from langchain.agents import create_agent
from policy_engine import GovernancePolicy
from policy_engine.adapters.langchain import LangChainKernel

policy = GovernancePolicy(blocked_patterns=["DROP TABLE"])
agent = create_agent(
    model="openai:gpt-4o-mini",
    tools=[],
    middleware=[LangChainKernel(policy).as_middleware()],
)
result = agent.invoke({"messages": [{"role": "user", "content": "hello"}]})
print(result["messages"][-1].content)
```

### Microsoft Agent Framework

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

See [[Adapter-API-Shape]] for the per-SDK reasoning behind each noun.
