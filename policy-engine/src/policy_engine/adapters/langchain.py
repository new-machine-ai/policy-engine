"""LangChain adapter — LangChainKernel + AgentMiddleware factory.

``LangChainKernel`` exposes ``create_context`` + ``pre_execute`` for callers
that want to write their own ``pre_model_hook``.  ``as_middleware()`` returns
a ready-to-plug LangChain ``AgentMiddleware`` for the ``create_agent(...,
middleware=[...])`` surface in LangChain 1.x — no manual hook required.
"""

from __future__ import annotations

from typing import Any

from policy_engine.audit import audit
from policy_engine.kernel import BaseKernel
from policy_engine.policy import PolicyRequest, PolicyViolationError

__all__ = ["LangChainKernel"]


def _last_user_text(messages: Any) -> str:
    if not messages:
        return ""
    for msg in reversed(messages):
        role = getattr(msg, "type", None) or getattr(msg, "role", None)
        content: Any = getattr(msg, "content", None)
        if role is None and isinstance(msg, tuple) and len(msg) == 2:
            role, content = msg
        elif role is None and isinstance(msg, dict):
            role = msg.get("role") or msg.get("type")
            content = msg.get("content")
        if role not in ("human", "user"):
            continue
        return str(content or "")
    return ""


class LangChainKernel(BaseKernel):
    framework = "langchain"

    def as_middleware(self, *, name: str = "langchain") -> Any:
        """Return a LangChain ``AgentMiddleware`` that gates ``before_model``.

        Plug into ``create_agent(model=..., tools=..., middleware=[...])``.
        Raises :class:`PolicyViolationError` when the policy blocks a request.
        """
        from langchain.agents.middleware import AgentMiddleware

        kernel = self
        ctx = self.create_context(name)

        class _PolicyMiddleware(AgentMiddleware):
            def before_model(self, state: Any, runtime: Any) -> Any:
                payload = _last_user_text(state.get("messages") if hasattr(state, "get") else state["messages"])
                decision = kernel.evaluate(
                    ctx,
                    PolicyRequest(payload=payload, phase="before_model"),
                )
                if not decision.allowed:
                    detail = decision.reason or "blocked"
                    audit("langchain", "before_model", "BLOCKED", detail, decision=decision)
                    raise PolicyViolationError(detail, pattern=decision.matched_pattern)
                audit("langchain", "before_model", "ALLOWED", name, decision=decision)
                return None

        return _PolicyMiddleware()
