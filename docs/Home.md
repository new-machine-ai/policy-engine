# Policy-Engine Adapter Wiki

`policy_engine` is a small, stdlib-only governance kernel. It enforces:

- prompt-pattern blocking
- tool allow/deny
- per-context call-count rate limit
- human-approval gating
- a structured audit trail

...and exposes that one decision through **ten thin adapters** (nine host/framework SDK surfaces plus an Agent-OS backend bridge).

## Start here

- [[Core-Concepts]] — how `BaseKernel.evaluate` works and the four adapter patterns
- [[Seam-Taxonomy]] — at-a-glance comparison of where each adapter plugs in
- [[Adapter-API-Shape]] — why adapters expose `as_*` versus `governed_*`

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
| Google ADK | Callback/plugin factory | [[Google-ADK-Adapter]] |
| Agent-OS (backend) | BaseKernel subclass | [[Agent-OS-Backend-Adapter]] |

## Layout

Each Python adapter lives at `policy-engine/src/policy_engine/adapters/<name>.py` and has a matching demo at `policy_engine_demos/<name>_governed.py` when the example is deterministic. Live hello-world examples live in `policy_engine_hello_world_multi_real/`.
