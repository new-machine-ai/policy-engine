"""CrewAI adapter — CrewAIKernel exposes create_context + pre_execute.

The demo registers @before_llm_call / @after_llm_call decorators that call
kernel.pre_execute(); no crew wrapping is needed.
"""

from policy_engine.kernel import BaseKernel

__all__ = ["CrewAIKernel"]


class CrewAIKernel(BaseKernel):
    framework = "crewai"
