"""Anthropic SDK adapter — message hook around ``messages.create``.

Seam: the Anthropic Python SDK does not expose middleware.  The adapter
provides ``AnthropicKernel.as_message_hook()`` so callers can govern an
individual ``client.messages.create(...)`` call without wrapping the client.
"""

from __future__ import annotations

from typing import Any

from policy_engine.audit import audit
from policy_engine.context import ExecutionContext
from policy_engine.kernel import BaseKernel
from policy_engine.policy import (
    GovernancePolicy,
    PolicyRequest,
    PolicyViolationError,
)

__all__ = [
    "AnthropicKernel",
    "GovernanceMessageHook",
    "GovernancePolicy",
    "PolicyViolationError",
]


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
            else:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    text = getattr(content, "text", None)
    if isinstance(text, str):
        return text
    return str(content) if content is not None else ""


def _iter_message_texts(messages: Any) -> list[str]:
    if messages is None:
        return []
    texts: list[str] = []
    for message in messages:
        if isinstance(message, dict):
            text = _content_to_text(message.get("content", ""))
        else:
            text = _content_to_text(getattr(message, "content", ""))
        if text:
            texts.append(text)
    return texts


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        name = tool.get("name")
        return str(name) if name else None
    name = getattr(tool, "name", None)
    return str(name) if name else None


class AnthropicKernel(BaseKernel):
    """Governance kernel for raw Anthropic Messages API calls."""

    framework = "anthropic"

    def __init__(self, policy: GovernancePolicy) -> None:
        super().__init__(policy)

    def as_message_hook(
        self,
        *,
        name: str = "anthropic-governance",
    ) -> "GovernanceMessageHook":
        return GovernanceMessageHook(self, name=name)


class GovernanceMessageHook:
    """Small, explicit gate for ``client.messages.create`` calls."""

    def __init__(self, kernel: AnthropicKernel, *, name: str) -> None:
        self._kernel = kernel
        self._name = name
        self._ctx = kernel.create_context(name)

    @property
    def kernel(self) -> AnthropicKernel:
        return self._kernel

    @property
    def context(self) -> ExecutionContext:
        return self._ctx

    def _evaluate_or_raise(self, request: PolicyRequest, *, phase: str) -> None:
        decision = self._kernel.evaluate(self._ctx, request)
        if not decision.allowed:
            detail = decision.reason or "blocked"
            audit("anthropic", phase, "BLOCKED", detail, decision=decision)
            raise PolicyViolationError(detail, pattern=decision.matched_pattern)
        detail = f"tool={request.tool_name}" if request.tool_name else self._name
        audit("anthropic", phase, "ALLOWED", detail, decision=decision)

    def create(self, client: Any, **kwargs: Any) -> Any:
        """Govern and delegate one Anthropic ``messages.create`` request."""
        for text in _iter_message_texts(kwargs.get("messages", [])):
            self._evaluate_or_raise(
                PolicyRequest(payload=text, phase="messages.create"),
                phase="messages.create",
            )

        for tool in kwargs.get("tools") or []:
            name = _tool_name(tool)
            if name is None:
                continue
            self._evaluate_or_raise(
                PolicyRequest(payload="", tool_name=name, phase="tool_request"),
                phase="tool_request",
            )

        response = client.messages.create(**kwargs)

        for block in getattr(response, "content", []) or []:
            block_type = getattr(block, "type", None)
            if block_type != "tool_use":
                continue
            name = getattr(block, "name", None)
            if not name:
                continue
            self._evaluate_or_raise(
                PolicyRequest(payload="", tool_name=str(name), phase="tool_use"),
                phase="tool_use",
            )

        audit(
            "anthropic",
            "messages.response",
            "ALLOWED",
            self._name,
            policy=self._kernel.policy.name,
        )
        return response
