"""Tests for the Google ADK adapter.

These tests use fake callback inputs and do not import or call Google ADK.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from policy_engine import AUDIT, GovernancePolicy, reset_audit  # noqa: E402
from policy_engine.adapters.google_adk import GoogleADKKernel  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_audit():
    reset_audit()
    yield
    reset_audit()


def test_before_tool_allows_safe_call_and_records_audit() -> None:
    kernel = GoogleADKKernel(
        GovernancePolicy(name="adk-test", allowed_tools=["search"])
    )

    result = kernel.before_tool_callback(
        tool_name="search",
        tool_args={"query": "AI governance best practices"},
        agent_name="adk-agent",
    )

    assert result is None
    entry = AUDIT[-1]
    assert entry["framework"] == "google_adk"
    assert entry["phase"] == "before_tool"
    assert entry["status"] == "ALLOWED"
    assert entry["policy"] == "adk-test"
    assert entry["tool_name"] == "search"
    assert "payload_hash" in entry


def test_before_tool_blocks_explicitly_blocked_tool() -> None:
    kernel = GoogleADKKernel(
        GovernancePolicy(name="adk-test", blocked_tools=["shell"])
    )

    result = kernel.before_tool_callback(
        tool_name="shell",
        tool_args={},
        agent_name="adk-agent",
    )

    assert result is not None
    assert "blocked_tool:shell" in result["error"]
    violation = kernel.get_violations()[0]
    assert violation.policy_name == "adk-test"
    assert violation.description == "blocked_tool:shell"
    assert AUDIT[-1]["status"] == "BLOCKED"


def test_before_tool_blocks_tool_not_in_allowlist() -> None:
    kernel = GoogleADKKernel(
        GovernancePolicy(name="adk-test", allowed_tools=["search", "summarize"])
    )

    result = kernel.before_tool_callback(
        tool_name="web_scraper",
        tool_args={},
        agent_name="adk-agent",
    )

    assert result is not None
    assert "tool_not_allowed:web_scraper" in result["error"]
    assert kernel.get_violations()[0].description == "tool_not_allowed:web_scraper"


def test_before_tool_blocks_pattern_in_tool_args_without_raw_audit_text() -> None:
    kernel = GoogleADKKernel(
        GovernancePolicy(
            name="adk-test",
            allowed_tools=["search"],
            blocked_patterns=["DROP TABLE"],
        )
    )

    result = kernel.before_tool_callback(
        tool_name="search",
        tool_args={"query": "DROP TABLE sessions; SELECT 1"},
        agent_name="adk-agent",
    )

    assert result is not None
    assert "blocked_pattern:DROP TABLE" in result["error"]
    entry = AUDIT[-1]
    assert entry["reason"] == "blocked_pattern:DROP TABLE"
    assert "payload_hash" in entry
    assert "sessions" not in str(entry)
    assert "sessions" not in str(kernel.get_audit_log()[-1].details)


def test_before_tool_supports_adk_agent_callback_args_shape() -> None:
    kernel = GoogleADKKernel(
        GovernancePolicy(name="adk-test", allowed_tools=["search"])
    )
    tool = SimpleNamespace(name="search")
    tool_context = SimpleNamespace(agent_name="adk-agent")

    result = kernel.before_tool_callback(
        tool=tool,
        args={"query": "AI governance"},
        tool_context=tool_context,
    )

    assert result is None
    assert AUDIT[-1]["tool_name"] == "search"


def test_after_tool_blocks_unsafe_result_text() -> None:
    kernel = GoogleADKKernel(
        GovernancePolicy(name="adk-test", blocked_patterns=["DROP TABLE"])
    )

    result = kernel.after_tool_callback(
        tool_name="search",
        tool_response={"answer": "DROP TABLE invoices"},
        agent_name="adk-agent",
    )

    assert result is not None
    assert "blocked_pattern:DROP TABLE" in result["error"]
    assert "invoices" not in str(AUDIT[-1])


def test_on_violation_receives_policy_violation() -> None:
    seen = []
    kernel = GoogleADKKernel(
        GovernancePolicy(name="adk-test", blocked_tools=["shell"]),
        on_violation=seen.append,
    )

    kernel.before_tool_callback(tool_name="shell", tool_args={}, agent_name="adk")

    assert len(seen) == 1
    assert seen[0].description == "blocked_tool:shell"


def test_as_callbacks_returns_adk_callback_keys() -> None:
    callbacks = GoogleADKKernel(
        GovernancePolicy(name="adk-test")
    ).as_callbacks()

    assert set(callbacks) == {"before_tool_callback", "after_tool_callback"}
    assert callable(callbacks["before_tool_callback"])
    assert callable(callbacks["after_tool_callback"])
