"""ExecutionContext — minimal per-run state."""

from dataclasses import dataclass, field

from policy_engine.policy import GovernancePolicy
from policy_engine.rate_limit import TokenBucket


@dataclass
class ExecutionContext:
    name: str
    policy: GovernancePolicy
    call_count: int = 0
    rate_bucket: TokenBucket | None = field(default=None)
