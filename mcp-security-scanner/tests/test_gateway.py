from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from policy_engine import GovernancePolicy

from mcp_security_scanner import (
    ApprovalStatus,
    MCPGateway,
    ParameterScopeRule,
    TimeWindowRule,
)


def test_gateway_allows_safe_tool_call_and_records_hash_only():
    gateway = MCPGateway(
        GovernancePolicy(name="mcp", allowed_tools=["search"], blocked_patterns=["DROP TABLE"])
    )

    decision = gateway.evaluate_tool_call("agent-1", "search", {"query": "hello"})

    assert decision.allowed is True
    assert decision.reason == "allowed"
    assert gateway.get_agent_call_count("agent-1") == 1
    audit_text = repr(gateway.audit_log)
    assert "hello" not in audit_text
    assert "payload_hash" in audit_text


def test_gateway_blocks_tool_outside_allowlist_and_blocked_pattern():
    gateway = MCPGateway(
        GovernancePolicy(
            name="mcp",
            allowed_tools=["search"],
            blocked_patterns=["DROP TABLE"],
        )
    )

    denied_tool = gateway.evaluate_tool_call("agent-1", "delete", {})
    denied_pattern = gateway.evaluate_tool_call("agent-1", "search", {"query": "DROP TABLE users"})

    assert denied_tool.allowed is False
    assert denied_tool.reason == "tool_not_allowed:delete"
    assert denied_pattern.allowed is False
    assert denied_pattern.reason == "blocked_pattern:DROP TABLE"
    assert gateway.get_agent_call_count("agent-1") == 0


def test_gateway_enforces_max_tool_calls():
    gateway = MCPGateway(GovernancePolicy(name="mcp", max_tool_calls=1))

    first = gateway.evaluate_tool_call("agent-1", "search", {})
    second = gateway.evaluate_tool_call("agent-1", "search", {})

    assert first.allowed is True
    assert second.allowed is False
    assert second.reason == "max_tool_calls exceeded"


def test_gateway_human_approval_for_sensitive_tool():
    pending_gateway = MCPGateway(
        GovernancePolicy(name="mcp"),
        sensitive_tools=["wire_transfer"],
    )
    approved_gateway = MCPGateway(
        GovernancePolicy(name="mcp"),
        sensitive_tools=["wire_transfer"],
        approval_callback=lambda *_args: ApprovalStatus.APPROVED,
    )
    denied_gateway = MCPGateway(
        GovernancePolicy(name="mcp"),
        sensitive_tools=["wire_transfer"],
        approval_callback=lambda *_args: ApprovalStatus.DENIED,
    )

    pending = pending_gateway.evaluate_tool_call("agent-1", "wire_transfer", {})
    approved = approved_gateway.evaluate_tool_call("agent-1", "wire_transfer", {})
    denied = denied_gateway.evaluate_tool_call("agent-1", "wire_transfer", {})

    assert pending.allowed is False
    assert pending.approval_status == ApprovalStatus.PENDING
    assert approved.allowed is True
    assert approved.approval_status == ApprovalStatus.APPROVED
    assert denied.allowed is False
    assert denied.approval_status == ApprovalStatus.DENIED


def test_policy_require_human_approval_can_continue_after_approval():
    gateway = MCPGateway(
        GovernancePolicy(name="mcp", require_human_approval=True),
        approval_callback=lambda *_args: ApprovalStatus.APPROVED,
    )

    decision = gateway.evaluate_tool_call("agent-1", "search", {"query": "safe"})

    assert decision.allowed is True
    assert decision.approval_status == ApprovalStatus.APPROVED
    assert gateway.get_agent_call_count("agent-1") == 1


def test_time_window_rule_blocks_outside_market_hours():
    gateway = MCPGateway(
        GovernancePolicy(name="trading", allowed_tools=["place_trade"]),
        context_rules=[
            TimeWindowRule(
                name="market_hours",
                timezone="America/New_York",
                start="09:30",
                end="16:00",
                weekdays=(0, 1, 2, 3, 4),
                tools=("place_trade",),
            )
        ],
    )

    inside = gateway.evaluate_tool_call(
        "agent-1",
        "place_trade",
        {"symbol": "MSFT"},
        now=datetime(2026, 5, 1, 10, 0, tzinfo=ZoneInfo("America/New_York")),
    )
    outside = gateway.evaluate_tool_call(
        "agent-1",
        "place_trade",
        {"symbol": "MSFT"},
        now=datetime(2026, 5, 2, 10, 0, tzinfo=ZoneInfo("America/New_York")),
    )

    assert inside.allowed is True
    assert outside.allowed is False
    assert outside.context_rule == "market_hours"
    assert "outside allowed weekdays" in outside.reason


def test_parameter_scope_rule_blocks_out_of_scope_values():
    gateway = MCPGateway(
        GovernancePolicy(name="files", allowed_tools=["read_file"]),
        context_rules=[
            ParameterScopeRule(
                name="workspace_scope",
                parameter="path",
                tools=("read_file",),
                allowed_prefixes=("/workspace/",),
            )
        ],
    )

    allowed = gateway.evaluate_tool_call("agent-1", "read_file", {"path": "/workspace/a.txt"})
    denied = gateway.evaluate_tool_call("agent-1", "read_file", {"path": "/etc/passwd"})

    assert allowed.allowed is True
    assert denied.allowed is False
    assert denied.context_rule == "workspace_scope"
    assert gateway.get_agent_call_count("agent-1") == 1


def test_intercept_tool_call_returns_agt_compatible_tuple():
    gateway = MCPGateway(GovernancePolicy(name="mcp", blocked_tools=["shell"]))

    allowed, reason = gateway.intercept_tool_call("agent-1", "shell", {})

    assert allowed is False
    assert reason == "blocked_tool:shell"


def test_gateway_fails_closed_on_rule_error():
    @dataclass
    class BrokenRule:
        name: str = "broken"

        def evaluate(self, _context):
            raise RuntimeError("boom")

    gateway = MCPGateway(
        GovernancePolicy(name="mcp"),
        context_rules=[BrokenRule()],
    )

    decision = gateway.evaluate_tool_call("agent-1", "search", {})

    assert decision.allowed is False
    assert decision.reason == "gateway_error_fail_closed"
    assert gateway.get_agent_call_count("agent-1") == 0

