"""ExecutionContext — minimal per-run state."""

from dataclasses import dataclass

from policy_engine.policy import GovernancePolicy


@dataclass
class ExecutionContext:
    name: str
    policy: GovernancePolicy
    call_count: int = 0
