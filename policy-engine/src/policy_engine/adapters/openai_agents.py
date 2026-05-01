"""OpenAI Agents SDK adapter — OpenAIAgentsKernel + governed Runner.

``OpenAIAgentsKernel.governed_runner(Runner)`` returns a drop-in replacement
for the SDK's ``Runner`` class whose ``.run(...)`` method evaluates the
policy before delegating. ``wrap_runner`` is retained as a back-compat alias.
"""

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

    def governed_runner(self, runner_cls: type) -> type:
        """Return a drop-in replacement for ``runner_cls`` whose ``run`` method
        evaluates the policy before delegating to the original runner."""
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

    # Back-compat alias for callers written against the older API.
    wrap_runner = governed_runner
