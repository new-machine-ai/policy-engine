"""OpenAI Agents SDK adapter — OpenAIAgentsKernel + wrapped Runner."""

from typing import Any, Callable

from policy_engine.kernel import BaseKernel
from policy_engine.policy import GovernancePolicy, PolicyViolationError

__all__ = [
    "OpenAIAgentsKernel",
    "GovernancePolicy",
    "PolicyViolationError",
]


class OpenAIAgentsKernel(BaseKernel):
    framework = "openai_agents"

    def __init__(
        self,
        policy: GovernancePolicy,
        on_violation: Callable[[PolicyViolationError], None] | None = None,
    ) -> None:
        super().__init__(policy)
        self._on_violation = on_violation
        self._ctx = self.create_context("openai-agents")

    def wrap(self, agent: Any) -> Any:
        """Tool allow/deny is enforced by the wrapped Runner; the agent itself
        is returned unchanged so the SDK still recognizes it."""
        return agent

    def wrap_runner(self, runner_cls: type) -> type:
        kernel = self

        class GovernedRunner:
            @staticmethod
            async def run(agent: Any, input_text: str, **kwargs: Any) -> Any:
                allowed, reason = kernel.pre_execute(kernel._ctx, input_text)
                if not allowed:
                    err = PolicyViolationError(reason or "blocked")
                    if kernel._on_violation is not None:
                        kernel._on_violation(err)
                    raise err
                return await runner_cls.run(agent, input_text, **kwargs)

        return GovernedRunner
