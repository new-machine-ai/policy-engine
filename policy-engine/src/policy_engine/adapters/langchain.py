"""LangChain adapter — LangChainKernel exposes create_context + pre_execute.

The demo writes its own pre_model_hook that calls kernel.pre_execute(); no
agent wrapping is needed.
"""

from policy_engine.kernel import BaseKernel

__all__ = ["LangChainKernel"]


class LangChainKernel(BaseKernel):
    framework = "langchain"
