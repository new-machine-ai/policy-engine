# Core Concepts

> Source: `policy-engine/src/policy_engine/kernel.py` and `policy-engine/src/policy_engine/policy.py`.

## `BaseKernel.evaluate`

Every adapter ultimately routes through this method. The check order is fixed:

1. `ctx.call_count >= policy.max_tool_calls` → BLOCKED `("max_tool_calls exceeded")`
2. `tool_name in policy.blocked_tools` → BLOCKED `("blocked_tool:<name>")`
3. `tool_name not in policy.allowed_tools` (if set) → BLOCKED `("tool_not_allowed:<name>")`
4. `policy.require_human_approval` → BLOCKED `("human_approval_required")`
5. `policy.matches_pattern(payload) is not None` → BLOCKED `("blocked_pattern:<pattern>")`
6. otherwise: `ctx.call_count += 1` → ALLOWED

Two entry points:

```python
BaseKernel.evaluate(ctx, request: PolicyRequest | str) -> PolicyDecision
BaseKernel.pre_execute(ctx, payload: str) -> tuple[bool, str | None]   # thin wrapper
```

`PolicyDecision` carries: `allowed`, `reason`, `policy`, `matched_pattern`, `tool_name`, `requires_approval`, `payload_hash`, `phase`. **Adapters never store the raw prompt** — only the SHA-256 hash.

## `GovernancePolicy`

```python
GovernancePolicy(
    name: str,
    blocked_patterns: list[str] = [],          # case-insensitive substring match
    max_tool_calls: int = sys.maxsize,
    require_human_approval: bool = False,
    allowed_tools: list[str] | None = None,    # None = no allowlist enforced
    blocked_tools: list[str] | None = None,    # None = no denylist
)
```

## Adapter patterns

| Pattern | What ships | Adapters |
|---|---|---|
| Method-proxy wrap | A wrapper class whose entry-point methods call `pre_execute` before delegating | `openai_assistants`, `pydantic_ai`, `openai_agents` (Runner only) |
| Hook/middleware factory | A closure, list, or explicit hook object that gates the host call | `claude`, `maf`, `anthropic` |
| Bare kernel | `BaseKernel` re-exported under a `framework` name; the *demo* writes the framework hook | `langchain`, `crewai` |
| Backend bridge | `BaseKernel`-compatible facade over a richer external policy engine | `agent_os` |

See [[Seam-Taxonomy]] for the side-by-side comparison.
