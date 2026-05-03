# runaway-cost

Standalone controls for runaway retries, tool-call loops, token spend, and cascading agent failures.

`runaway-cost` is stdlib-only at runtime. It does not depend on Agent-OS, Agent Hypervisor, Agent SRE, `policy-engine`, or any sibling package.

## Install

```bash
pip install -e ./runaway-cost
```

Optional test dependency:

```bash
pip install -e "./runaway-cost[test]"
```

## Guard Quickstart

```python
from runaway_cost import BudgetPolicy, RunawayCostGuard

guard = RunawayCostGuard(
    budget_policy=BudgetPolicy(max_tokens=1_000, max_tool_calls=20, max_cost_usd=0.50)
)

decision = guard.evaluate_attempt(
    "agent-1",
    "session-1",
    "call_model",
    estimated_tokens=200,
    estimated_cost_usd=0.03,
)
assert decision.allowed

guard.record_success("agent-1", "session-1", tokens=200, cost_usd=0.03)
```

The guard checks circuit state first, then per-agent ring limits, sliding-window limits, and projected budget. Decisions include retry/wait hints, budget status, rate-limit status, circuit state, and audit-safe metadata hashes.

## CLI

```bash
PYTHONPATH=runaway-cost/src python -m runaway_cost.cli check \
  --agent-id agent-1 --session-id session-1 --operation call_model \
  --tokens 100 --cost-usd 0.01 --format json

PYTHONPATH=runaway-cost/src python -m runaway_cost.cli simulate-retries \
  --max-attempts 3 --failures 5 --format json
```

Denied budget, rate, or circuit checks return nonzero.

## Runnable Examples

```bash
PYTHONPATH=runaway-cost/src python runaway-cost/examples/token_bucket.py
PYTHONPATH=runaway-cost/src python runaway-cost/examples/sliding_window.py
PYTHONPATH=runaway-cost/src python runaway-cost/examples/agent_rate_limiter.py
PYTHONPATH=runaway-cost/src python runaway-cost/examples/budget_exhaustion.py
PYTHONPATH=runaway-cost/src python runaway-cost/examples/retry_policy.py
PYTHONPATH=runaway-cost/src python runaway-cost/examples/circuit_breaker_recovery.py
PYTHONPATH=runaway-cost/src python runaway-cost/examples/cascade_detector.py
PYTHONPATH=runaway-cost/src python runaway-cost/examples/runaway_guard.py
```

## Public API

- Rate limits: `RateLimitConfig`, `RateLimitExceeded`, `TokenBucket`, `RateLimitStatus`, `RateLimiter`, `SlidingWindowRateLimiter`, `ExecutionRing`, `AgentRateLimiter`, `RateLimitStats`
- Budgets: `BudgetPolicy`, `BudgetTracker`, `BudgetStatus`, `TokenBudgetTracker`, `TokenBudgetStatus`
- Circuit breakers: `CircuitState`, `CircuitBreakerConfig`, `CircuitBreaker`, `CircuitOpenError`, `CascadeDetector`
- Retry control: `RetryPolicy`, `RetryState`, `RetryEvent`, `RetryExhausted`, `retry`
- Facade: `RunawayCostGuard`, `RunawayDecision`

## Boundary

The package uses only Python stdlib at runtime and stores no raw prompts, arguments, responses, or schemas in guard decisions. Source-derived files preserve the Microsoft MIT copyright notice while replacing external runtime imports with local dataclasses, enums, and protocols.
