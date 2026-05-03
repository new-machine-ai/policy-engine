# Policy-Engine Adapter Wiki

`policy_engine` is a small, stdlib-only governance kernel. It enforces:

- prompt-pattern blocking
- tool allow/deny
- per-context call-count rate limit
- human-approval gating
- a structured audit trail

…and exposes that one decision through **nine thin adapters** (eight host/framework SDK surfaces plus an Agent-OS backend bridge).

## Start here

- [[Core-Concepts]] — how `BaseKernel.evaluate` works and the four adapter patterns
- [[Seam-Taxonomy]] — at-a-glance comparison of where each adapter plugs in
- [[Adapter-API-Shape]] — why each SDK gets a different noun in `kernel.governed_<noun>(...)`
- [[MCP-Security-Scanner]] — sibling package for MCP tool-definition scanning and runtime gateway checks
- [[Multi-Agent-Drift]] — sibling package for context budgets, drift, handoff safety, vector clocks, and saga fan-out
- [[Prompt-Injection]] — sibling package for prompt-injection and untrusted-content defenses
- [[Human-Loop]] — sibling package for approval gates, RBAC, kill switches, and reversibility checks
- [[Runaway-Cost]] — sibling package for rate limits, budgets, retries, circuit breakers, and cascade detection

## Adapters

| Framework | Pattern | Page |
|---|---|---|
| Microsoft Agent Framework | Middleware factory | [[MAF-Adapter]] |
| OpenAI Assistants | Method proxy | [[OpenAI-Assistants-Adapter]] |
| OpenAI Agents SDK | Method proxy + native hooks | [[OpenAI-Agents-SDK-Adapter]] |
| LangChain / LangGraph | Bare kernel | [[LangChain-Adapter]] |
| CrewAI | Bare kernel | [[CrewAI-Adapter]] |
| PydanticAI | Method proxy | [[PydanticAI-Adapter]] |
| Claude Agent SDK | Hook factory | [[Claude-Agent-SDK-Adapter]] |
| Anthropic SDK | Message hook | [[Anthropic-Adapter]] |
| Agent-OS (backend) | BaseKernel subclass | [[Agent-OS-Backend-Adapter]] |

## Layout

Each Python adapter lives at `policy-engine/src/policy_engine/adapters/<name>.py` and has a matching demo at `policy_engine_demos/<name>_governed.py`. The shared rulebook used by `run_all.py` is defined once in `policy_engine_demos/_shared.py` as `POLICY`.
