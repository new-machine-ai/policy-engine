"""BaseKernel — shared create_context + pre_execute backing every adapter."""

from policy_engine.context import ExecutionContext
from policy_engine.policy import GovernancePolicy, PolicyDecision, PolicyRequest
from policy_engine.rate_limit import TokenBucket


class BaseKernel:
    framework: str = "base"

    def __init__(self, policy: GovernancePolicy) -> None:
        policy.validate()
        self.policy = policy

    def create_context(self, name: str) -> ExecutionContext:
        bucket = (
            TokenBucket.from_config(self.policy.rate_limit)
            if self.policy.rate_limit is not None
            else None
        )
        return ExecutionContext(name=name, policy=self.policy, rate_bucket=bucket)

    def evaluate(
        self, ctx: ExecutionContext, request: PolicyRequest | str
    ) -> PolicyDecision:
        if isinstance(request, str):
            request = PolicyRequest(payload=request)

        payload = request.payload or ""
        payload_hash = request.payload_sha256()

        def decision(
            allowed: bool,
            reason: str | None = None,
            *,
            matched_pattern: str | None = None,
            requires_approval: bool = False,
        ) -> PolicyDecision:
            return PolicyDecision(
                allowed=allowed,
                reason=reason,
                policy=self.policy.name,
                matched_pattern=matched_pattern,
                tool_name=request.tool_name,
                requires_approval=requires_approval,
                payload_hash=payload_hash,
                phase=request.phase,
            )

        if ctx.call_count >= self.policy.max_tool_calls:
            return decision(False, "max_tool_calls exceeded")

        if request.tool_name is not None:
            if (
                self.policy.blocked_tools is not None
                and request.tool_name in self.policy.blocked_tools
            ):
                return decision(False, f"blocked_tool:{request.tool_name}")
            if (
                self.policy.allowed_tools is not None
                and request.tool_name not in self.policy.allowed_tools
            ):
                return decision(False, f"tool_not_allowed:{request.tool_name}")

        if self.policy.require_human_approval:
            return decision(
                False,
                "human_approval_required",
                requires_approval=True,
            )

        matched = self.policy.matches_pattern(payload)
        if matched is not None:
            return decision(False, f"blocked_pattern:{matched}", matched_pattern=matched)

        if ctx.rate_bucket is not None and not ctx.rate_bucket.consume():
            wait = ctx.rate_bucket.time_until_available()
            return decision(False, f"rate_limited:wait_{wait:.3f}s")

        ctx.call_count += 1
        return decision(True)

    def pre_execute(
        self, ctx: ExecutionContext, payload: str
    ) -> tuple[bool, str | None]:
        decision = self.evaluate(ctx, PolicyRequest(payload=payload))
        return decision.allowed, decision.reason
