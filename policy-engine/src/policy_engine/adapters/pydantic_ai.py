"""PydanticAI adapter — PydanticAIKernel.wrap(agent) -> wrapper."""

from typing import Any

from policy_engine.kernel import BaseKernel
from policy_engine.policy import GovernancePolicy, PolicyViolationError

__all__ = ["PydanticAIKernel", "PolicyViolationError"]


class _GovernedPydanticAgent:
    def __init__(self, kernel: "PydanticAIKernel", agent: Any) -> None:
        self._kernel = kernel
        self._agent = agent
        self._ctx = kernel.create_context("pydantic-ai")

    async def run(self, prompt: str, **kwargs: Any) -> Any:
        allowed, reason = self._kernel.pre_execute(self._ctx, prompt)
        if not allowed:
            raise PolicyViolationError(reason or "blocked")
        return await self._agent.run(prompt, **kwargs)


class PydanticAIKernel(BaseKernel):
    framework = "pydantic_ai"

    def __init__(self, policy: GovernancePolicy) -> None:
        super().__init__(policy)

    def wrap(self, agent: Any) -> _GovernedPydanticAgent:
        return _GovernedPydanticAgent(self, agent)
