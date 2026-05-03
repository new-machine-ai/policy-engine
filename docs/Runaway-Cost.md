# Runaway Cost

`runaway-cost/` is a sibling package for rate limits, retry limits, token/cost budgets, timeouts, circuit breakers, and cascade detection.

## Capabilities

- Token-bucket and sliding-window rate limits
- Per-agent execution-ring limits
- Token, tool-call, cost, duration, and retry budgets
- Token budget warning callbacks
- Sync and async circuit breakers with half-open recovery
- Retry decorator with exponential backoff, selected exceptions, and elapsed-time caps
- Cascade detection across open agent circuits
- `RunawayCostGuard` facade for combined preflight decisions

## Quickstart

```bash
PYTHONPATH=runaway-cost/src \
  python -m runaway_cost.cli check --agent-id agent-1 --session-id session-1 --operation call_model --tokens 100 --cost-usd 0.01 --format json
```

Denied budget, rate, or circuit checks return nonzero.

## Package Boundary

The package has no runtime dependencies, no live model credentials, and no dependency on sibling packages. Configuration examples use JSON or Python APIs.
