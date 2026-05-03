# Multi-Agent Drift

`multi-agent-drift/` is a sibling package for multi-agent context budgets, conversation drift detection, handoff safety, vector clocks, and saga/fan-out orchestration.

It is intentionally separate from `policy-engine/`: policy-engine remains the runtime policy kernel, while this package focuses on multi-agent coordination failure modes such as policy/config drift, escalation loops, stale handoffs, lock contention, causal ordering, and saga compensation.

## What It Includes

- Context budget scheduling with `SIGRESUME`, `SIGWARN`, and `SIGSTOP`
- Conversation guardian alerts for escalation, offensive intent, retry loops, and conversation length
- Drift reports for config, policy, trust, version, and capability differences
- Intent locks with read/write/exclusive contention
- Vector clocks with `happens_before` and `is_concurrent`
- Saga orchestration and fan-out policies
- `MultiAgentDriftMonitor` facade and `multi-agent-drift` CLI

## Quickstart

```bash
PYTHONPATH=multi-agent-drift/src \
  python -m multi_agent_drift.cli scan multi-agent-drift/examples/drift_scenario.json --format json
```

The scanner exits nonzero when critical drift or critical conversation alerts are found.

## Package Boundary

The package has no hard dependency on Agent-OS, Agent Hypervisor, policy-engine, or live model credentials. It can be used beside the policy-engine demos or embedded into a larger agent runtime.
