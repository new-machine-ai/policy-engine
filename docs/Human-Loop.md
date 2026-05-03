# Human Loop

`human-loop/` is a sibling package for human approval, role gates, kill-switch controls, and reversibility checks for irreversible agent actions.

## Capabilities

- Human approval requests with in-memory or webhook-backed approval queues
- Timeout defaults, approval fatigue detection, and M-of-N quorum
- Local RBAC roles and role policy templates
- `SIGSTOP`/`SIGKILL` kill-switch behavior with handoff or compensation markers
- Reversibility classification and registry entries for execute/undo APIs
- `HumanLoopGuard` facade for kill-state, RBAC, reversibility, and approval checks

## Quickstart

```bash
PYTHONPATH=human-loop/src \
  python -m human_loop.cli check-action --agent-id agent-1 --session-id session-1 --action deploy --role admin --format json
```

Unapproved irreversible actions return a nonzero exit code.

## Package Boundary

The package has no dependency on external governance runtimes or live model credentials. It replaces external model imports with local dataclasses and protocols.
