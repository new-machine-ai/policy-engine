# human-loop

Standalone human approval, role gates, kill-switch controls, and reversibility checks for irreversible agent actions.

This package ports Agent Governance Toolkit concepts into a sibling package with no dependency on external agent governance runtimes.

## Install

```bash
pip install -e ./human-loop
```

Optional YAML support:

```bash
pip install -e "./human-loop[yaml]"
```

## Irreversible Action Gate

```python
from human_loop import HumanLoopGuard, Role

guard = HumanLoopGuard()
guard.rbac.assign_role("agent-1", Role.ADMIN)

decision = guard.evaluate_action("agent-1", "session-1", "deploy")
assert not decision.allowed
assert decision.request is not None
```

The guard evaluates kill-state, RBAC permission, reversibility, and human approval in that order.

## Kill Switch

```python
from human_loop import KillReason, KillSignal, KillSwitch

switch = KillSwitch()
switch.kill("agent-1", "session-1", KillReason.MANUAL, signal=KillSignal.SIGSTOP)
assert switch.is_stopped("agent-1")
```

`SIGSTOP` blocks future action gates without terminating the process callback. `SIGKILL` invokes the registered termination callback and records handoff or compensation state for in-flight steps.

## CLI

```bash
PYTHONPATH=human-loop/src python -m human_loop.cli classify --action deploy --format json
PYTHONPATH=human-loop/src python -m human_loop.cli check-action --agent-id agent-1 --session-id session-1 --action deploy --role admin --format json
PYTHONPATH=human-loop/src python -m human_loop.cli kill --agent-id agent-1 --session-id session-1 --signal sigstop --reason manual
```

Denied, killed, or unapproved irreversible action checks return a nonzero exit code.

## Runnable Examples

```bash
PYTHONPATH=human-loop/src python human-loop/examples/irreversible_deploy.py
PYTHONPATH=human-loop/src python human-loop/examples/rbac_reader_denied.py
PYTHONPATH=human-loop/src python human-loop/examples/quorum_approval.py
PYTHONPATH=human-loop/src python human-loop/examples/timeout_default_deny.py
PYTHONPATH=human-loop/src python human-loop/examples/kill_switch.py
PYTHONPATH=human-loop/src python human-loop/examples/reversibility_registry.py
```

## Public API

- Human approval: `EscalationHandler`, `EscalationPolicy`, `EscalationRequest`, `EscalationResult`, `EscalationDecision`, `DefaultTimeoutAction`, `QuorumConfig`, `ApprovalBackend`, `InMemoryApprovalQueue`, `WebhookApprovalBackend`
- Role gates: `Role`, `RolePolicy`, `RBACManager`
- Kill switch: `KillSwitch`, `KillReason`, `KillSignal`, `KillResult`, `StepHandoff`, `HandoffStatus`
- Reversibility: `ReversibilityChecker`, `ReversibilityAssessment`, `ReversibilityLevel`, `CompensatingAction`, `ReversibilityRegistry`, `ReversibilityEntry`, `ActionDescriptor`
- Facade: `HumanLoopGuard`

## Boundary

The package has no runtime dependency on other local products or external governance runtimes. Source-derived files preserve the Microsoft MIT copyright notice while replacing external models with local dataclasses and protocols.
