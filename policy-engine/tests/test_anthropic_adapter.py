"""Tests for the raw Anthropic SDK adapter.

These tests use fake clients and do not import or call the Anthropic SDK.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from policy_engine import AUDIT, GovernancePolicy, PolicyViolationError, reset_audit  # noqa: E402
from policy_engine.adapters.anthropic import AnthropicKernel  # noqa: E402


class FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="hello")])


class FakeClient:
    def __init__(self) -> None:
        self.messages = FakeMessages()


def test_message_hook_allows_safe_prompt_and_delegates() -> None:
    reset_audit()
    client = FakeClient()
    hook = AnthropicKernel(
        GovernancePolicy(name="anthropic-test", blocked_patterns=["DROP TABLE"])
    ).as_message_hook(name="test-hook")

    response = hook.create(
        client,
        model="claude-test",
        max_tokens=64,
        messages=[{"role": "user", "content": "Say hello."}],
    )

    assert response.content[0].text == "hello"
    assert len(client.messages.calls) == 1
    assert client.messages.calls[0]["model"] == "claude-test"
    first = AUDIT[0]
    assert first["framework"] == "anthropic"
    assert first["phase"] == "messages.create"
    assert first["status"] == "ALLOWED"
    assert first["policy"] == "anthropic-test"
    assert "payload_hash" in first
    assert "payload" not in first
    reset_audit()


def test_message_hook_blocks_prompt_before_client_call() -> None:
    reset_audit()
    client = FakeClient()
    hook = AnthropicKernel(
        GovernancePolicy(name="anthropic-test", blocked_patterns=["DROP TABLE"])
    ).as_message_hook()

    with pytest.raises(PolicyViolationError, match="blocked_pattern:DROP TABLE"):
        hook.create(
            client,
            model="claude-test",
            max_tokens=64,
            messages=[{"role": "user", "content": "Please DROP TABLE users"}],
        )

    assert client.messages.calls == []
    last = AUDIT[-1]
    assert last["status"] == "BLOCKED"
    assert last["reason"] == "blocked_pattern:DROP TABLE"
    assert "payload_hash" in last
    assert "Please DROP TABLE users" not in str(last)
    reset_audit()


def test_message_hook_allows_requested_tool_in_allowlist() -> None:
    reset_audit()
    client = FakeClient()
    hook = AnthropicKernel(
        GovernancePolicy(name="anthropic-tools", allowed_tools=["web_search"])
    ).as_message_hook()

    hook.create(
        client,
        model="claude-test",
        max_tokens=64,
        messages=[{"role": "user", "content": "Use search."}],
        tools=[{"name": "web_search", "description": "search", "input_schema": {}}],
    )

    assert len(client.messages.calls) == 1
    assert AUDIT[-2]["phase"] == "tool_request"
    assert AUDIT[-2]["status"] == "ALLOWED"
    assert AUDIT[-2]["tool_name"] == "web_search"
    reset_audit()


def test_message_hook_blocks_requested_tool_not_in_allowlist() -> None:
    reset_audit()
    client = FakeClient()
    hook = AnthropicKernel(
        GovernancePolicy(name="anthropic-tools", allowed_tools=["web_search"])
    ).as_message_hook()

    with pytest.raises(PolicyViolationError, match="tool_not_allowed:shell_exec"):
        hook.create(
            client,
            model="claude-test",
            max_tokens=64,
            messages=[{"role": "user", "content": "Use shell."}],
            tools=[{"name": "shell_exec", "description": "shell", "input_schema": {}}],
        )

    assert client.messages.calls == []
    assert AUDIT[-1]["phase"] == "tool_request"
    assert AUDIT[-1]["status"] == "BLOCKED"
    assert AUDIT[-1]["tool_name"] == "shell_exec"
    reset_audit()


def test_message_hook_blocks_requested_tool_in_blocklist() -> None:
    reset_audit()
    client = FakeClient()
    hook = AnthropicKernel(
        GovernancePolicy(name="anthropic-tools", blocked_tools=["shell_exec"])
    ).as_message_hook()

    with pytest.raises(PolicyViolationError, match="blocked_tool:shell_exec"):
        hook.create(
            client,
            model="claude-test",
            max_tokens=64,
            messages=[{"role": "user", "content": "Use shell."}],
            tools=[{"name": "shell_exec", "description": "shell", "input_schema": {}}],
        )

    assert client.messages.calls == []
    assert AUDIT[-1]["phase"] == "tool_request"
    assert AUDIT[-1]["status"] == "BLOCKED"
    assert AUDIT[-1]["tool_name"] == "shell_exec"
    reset_audit()
