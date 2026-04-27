"""OpenAI Assistants adapter — OpenAIKernel.wrap(assistant, client) -> proxy."""

from typing import Any

from policy_engine.kernel import BaseKernel
from policy_engine.policy import GovernancePolicy, PolicyViolationError

__all__ = ["OpenAIKernel", "GovernedAssistant", "PolicyViolationError"]


class GovernedAssistant:
    """Method-level proxy: every Assistants SDK call goes through policy first."""

    def __init__(self, kernel: "OpenAIKernel", assistant: Any, client: Any) -> None:
        self._kernel = kernel
        self._assistant = assistant
        self._client = client
        self._ctx = kernel.create_context(f"assistant:{assistant.id}")

    @property
    def id(self) -> str:
        return self._assistant.id

    def create_thread(self):
        return self._client.beta.threads.create()

    def add_message(self, thread_id: str, content: str, role: str = "user"):
        allowed, reason = self._kernel.pre_execute(self._ctx, content)
        if not allowed:
            raise PolicyViolationError(reason or "blocked")
        return self._client.beta.threads.messages.create(
            thread_id=thread_id, role=role, content=content
        )

    def run(self, thread_id: str):
        return self._client.beta.threads.runs.create_and_poll(
            thread_id=thread_id, assistant_id=self._assistant.id
        )

    def list_messages(self, thread_id: str, order: str = "desc", limit: int = 1):
        return self._client.beta.threads.messages.list(
            thread_id=thread_id, order=order, limit=limit
        )

    def delete_thread(self, thread_id: str):
        return self._client.beta.threads.delete(thread_id=thread_id)


class OpenAIKernel(BaseKernel):
    framework = "openai_assistants"

    def __init__(self, policy: GovernancePolicy) -> None:
        super().__init__(policy)

    def wrap(self, assistant: Any, client: Any) -> GovernedAssistant:
        return GovernedAssistant(self, assistant, client)
