# Adapter API Shape — why each SDK gets a different noun

Every policy-engine adapter exposes a one-line wire-up of the form
`Kernel(policy).<verb>_<noun>(...)`. The verb-and-noun choice is not
arbitrary — it tracks what the host SDK actually wants you to hand it
back. This page explains why the API surface looks the way it does,
and why the variation is honest rather than fixable.

> Companion pages: [[Core-Concepts]] for `BaseKernel.evaluate`
> mechanics; [[Seam-Taxonomy]] for a side-by-side table of *where*
> in the call stack each adapter actually evaluates the policy.

## TL;DR — two patterns

| Demo | Wire-up | Pattern |
|---|---|---|
| Anthropic Messages API | `AnthropicKernel(p).governed_client(client)` | `governed_<noun>(seed)` |
| Claude Agent SDK | `ClaudeSDKKernel(p).governed_options(opts)` | `governed_<noun>(seed)` |
| OpenAI Agents | `OpenAIAgentsKernel(p).governed_runner(Runner)` | `governed_<noun>(seed)` |
| LangChain 1.x | `LangChainKernel(p).as_middleware()` | `as_<noun>()` |
| MAF | `MAFKernel(p).as_middleware(agent_id=...)` | `as_<noun>(...)` |

The choice between `governed_<noun>` and `as_<noun>` reflects whether
the method **transforms a seed** or **constructs a fresh handle**:

- **`governed_<noun>(seed)`** — caller supplies an existing SDK object
  (a client, an options dataclass, a Runner class). The kernel returns
  a drop-in-but-policy-gated copy.
- **`as_<noun>()`** — caller supplies nothing. The kernel constructs a
  fresh middleware handle from its own policy state, ready to plug
  into the SDK's middleware list.

`as_<noun>` follows the established Python convention for "give me
this thing as a `<type>`" — see `dataclasses.asdict`,
`pathlib.Path.as_posix`, `concurrent.futures.as_completed`. It reads
naturally when there's no input object to transform.

## Why the noun has to vary

A *seam* is the hook point a host SDK provides for third parties to
intercept its calls without forking it. The seams in the wild fall
into a small number of shapes:

- **Middleware lists** (LangChain, MAF, ASP.NET Core, Express): you
  hand the SDK a callable that wraps `next()`.
- **Options objects with hook fields** (Claude Agent SDK): you hand
  the SDK a config struct whose `hooks` field is a callable map.
- **Runner / executor classes** (OpenAI Agents): you subclass or wrap
  the class the SDK uses to drive the agent loop.
- **Client objects** (raw Anthropic, raw OpenAI Chat Completions): no
  seam exists at all — the SDK is just an HTTP wrapper. The "seam" is
  the call site itself, so you wrap the client.

The seam dictates what kind of object you hand the SDK back. If the
SDK wants middleware, you must hand it middleware. If it wants
options, you must hand it options. There is no neutral type that
satisfies all five SDKs.

That's why the **noun** has to vary — `client`, `options`,
`middleware`, `runner` describe genuinely different objects with
genuinely different shapes. Collapsing them under one name would lie
about what the SDK actually receives.

## Case-by-case: what each SDK exposes

### Anthropic Messages API — no seam, only a call site

```python
import anthropic
client = anthropic.Anthropic()
response = client.messages.create(model=..., messages=[...])
```

The official `anthropic` Python package is a thin HTTP wrapper. There
is no middleware concept, no hook system, no `Options` dataclass with
callbacks, no event bus. The only place to enforce policy is at the
`messages.create` call site.

policy-engine therefore returns a **transparent client wrapper**:

```python
client = AnthropicKernel(POLICY).governed_client(anthropic.Anthropic())
response = client.messages.create(model=..., messages=[...])  # gated
client.beta.messages.create(...)                              # falls through
```

The wrapper proxies every attribute via `__getattr__`, so any future
Anthropic API surface remains accessible — only `.messages.create` is
intercepted. The verb is `governed_` because the caller hands in a
real client; the noun is `client` because *that's what comes back*.

### Claude Agent SDK — options object with a `hooks` field

```python
from claude_agent_sdk import ClaudeAgentOptions, query
options = ClaudeAgentOptions(
    system_prompt="...",
    hooks={"UserPromptSubmit": [HookMatcher(hooks=[...])], ...},
)
async for msg in query(prompt=..., options=options): ...
```

The Claude Agent SDK exposes ten event hooks (`UserPromptSubmit`,
`PreToolUse`, `PostToolUse`, …), but the *only* place you register
them is on `ClaudeAgentOptions.hooks`. There's no `Agent` object to
subclass and no middleware list to plug into.

policy-engine therefore returns a **`ClaudeAgentOptions` copy with the
governance hooks pre-merged into `opts.hooks`**:

```python
options = ClaudeSDKKernel(POLICY).governed_options(
    ClaudeAgentOptions(system_prompt="...", allowed_tools=[])
)
async for msg in query(prompt=..., options=options): ...
```

Existing entries in `opts.hooks` are preserved; the governance hook
is inserted at the front of each event's list. The verb is `governed_`
because the caller hands in their own `ClaudeAgentOptions`; the noun
is `options` because that's the only object the SDK accepts at this
seam.

### OpenAI Agents SDK — Runner class as the seam

```python
from agents import Agent, Runner
agent = Agent(name="...", model="...", instructions="...")
result = await Runner.run(agent, "prompt")
```

The OpenAI Agents SDK has `RunHooks` and `Guardrail` objects, but the
stable, public, single interception point is **`Runner`** — the class
that drives the agent loop. `Runner.run` is a class/static method, so
"wrapping" it means handing back a class with a compatible `.run()`.

policy-engine therefore returns a **wrapped `Runner` class**:

```python
runner = OpenAIAgentsKernel(POLICY).governed_runner(Runner)
result = await runner.run(agent, "prompt")
```

The returned class has the same `run(agent, input_text, **kwargs)`
shape as the original. The verb is `governed_` because the caller
hands in the real `Runner` class; the noun is `runner` because that's
the SDK's seam — there's no middleware list and no options dataclass
to hand back. (The previous name `wrap_runner` is retained as a
back-compat alias; new code should prefer `governed_runner`.)

### LangChain 1.x — first-class middleware

```python
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware

class MyMiddleware(AgentMiddleware):
    def before_model(self, state, runtime): ...

agent = create_agent(model=..., tools=[], middleware=[MyMiddleware()])
```

LangChain 1.x ships an `AgentMiddleware` base class with hooks for
`before_model`, `after_model`, `wrap_model_call`, `wrap_tool_call`,
etc. `create_agent(..., middleware=[...])` is the canonical seam.

policy-engine therefore returns an **`AgentMiddleware` instance**:

```python
agent = create_agent(
    model=...,
    tools=[],
    middleware=[LangChainKernel(POLICY).as_middleware()],
)
```

The middleware's `before_model` runs `kernel.evaluate` and raises
`PolicyViolationError` on block. The verb is `as_` (not `governed_`)
because the caller hands in nothing — the kernel constructs the
middleware fresh from its own policy state. The noun is `middleware`
because that's the seam name on the host SDK.

### Microsoft Agent Framework — async middleware pipeline

```python
from agent_framework import Agent, agent_middleware

@agent_middleware
async def my_middleware(context, next_):
    # ... pre-hook
    result = await next_(context)
    # ... post-hook
    return result

async with Agent(client=..., name=..., middleware=[my_middleware]) as agent:
    await agent.run(...)
```

MAF's seam is structurally similar to LangChain's — a middleware list
on the agent — but the callable shape and decorator are different.

policy-engine therefore returns a **list of MAF middleware callables**:

```python
middleware = MAFKernel(POLICY).as_middleware(agent_id="hello-maf")
async with Agent(client=..., name=..., middleware=middleware) as agent:
    await agent.run(...)
```

The list shape (rather than a single object) is dictated by MAF's
`middleware: list[...]` parameter and our existing
`create_governance_middleware(...)` factory — `as_middleware`
delegates to it. As with LangChain, the caller hands in nothing, so
the verb is `as_`.

## When to use which verb

The two-verb split is small but informational:

| Verb | Meaning | When the SDK's seam takes |
|---|---|---|
| `governed_<noun>(seed)` | "transform this SDK object into a policy-gated copy" | a real instance/class the caller already constructed |
| `as_<noun>()` / `as_<noun>(...)` | "construct a `<noun>` from this kernel's policy" | a fresh middleware/handle the SDK will plug in itself |

You can predict which verb an adapter exposes from the seam alone:

- If the SDK lets you construct an object and pass it in (a client, an
  options dataclass, a Runner class), `governed_<noun>` is right —
  there's a seed to transform.
- If the SDK wants you to hand it middleware that it will instantiate
  into its own pipeline, `as_<noun>` is right — there's nothing to
  transform, and `as_*` is the established Python idiom for "give me
  this thing as a `<type>`."

If a host SDK adds a new seam — e.g. raw Anthropic shipping a
middleware system — policy-engine grows a second helper alongside the
existing one. The `<verb>_<noun>` convention scales because it tracks
SDK reality rather than fighting it.

## What is the same across all five

- **One `BaseKernel`.** Every kernel subclasses `BaseKernel`, so
  `kernel.evaluate(ctx, request)` runs the same check order
  ([[Core-Concepts]]) regardless of SDK.
- **One audit trail.** Every adapter calls `audit("<framework>", ...)`
  with consistent `phase` / `status` semantics, so the unified
  `policy_engine.AUDIT` reads the same way for any SDK.
- **One policy.** A `GovernancePolicy` written for Anthropic enforces
  the same rules in MAF or LangChain — the noun is just plumbing.
- **One context.** The wire-up helpers internally create a single
  `ExecutionContext` per kernel call so `max_tool_calls` accounting
  is consistent within an SDK invocation.

So the noun varies, the verb varies between two coherent patterns,
and everything *behind* the seam — evaluation, audit, policy, context
— is identical. The variation lives only at the surface, where it
matches the host SDK's vocabulary.
