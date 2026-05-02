"""Unit tests for the bare-bones policy engine core."""

import asyncio
import hashlib
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from policy_engine import (  # noqa: E402
    AUDIT,
    BaseKernel,
    GovernancePolicy,
    PolicyDecision,
    PolicyRequest,
    PolicyViolationError,
    audit,
    reset_audit,
)


def _make() -> tuple[BaseKernel, "ExecutionContext"]:
    policy = GovernancePolicy(
        name="t",
        blocked_patterns=["DROP TABLE", "rm -rf"],
        max_tool_calls=10,
    )
    kernel = BaseKernel(policy)
    return kernel, kernel.create_context("test")


def test_matches_pattern_hit() -> None:
    p = GovernancePolicy(blocked_patterns=["DROP TABLE"])
    assert p.matches_pattern("please DROP TABLE users") == "DROP TABLE"


def test_matches_pattern_case_insensitive() -> None:
    p = GovernancePolicy(blocked_patterns=["DROP TABLE"])
    assert p.matches_pattern("drop table users") == "DROP TABLE"


def test_matches_pattern_miss() -> None:
    p = GovernancePolicy(blocked_patterns=["DROP TABLE"])
    assert p.matches_pattern("hello") is None


def test_matches_pattern_empty_text() -> None:
    p = GovernancePolicy(blocked_patterns=["x"])
    assert p.matches_pattern("") is None


def test_pre_execute_allows_safe_input() -> None:
    kernel, ctx = _make()
    allowed, reason = kernel.pre_execute(ctx, "Say hello.")
    assert allowed is True
    assert reason is None
    assert ctx.call_count == 1


def test_pre_execute_blocks_pattern() -> None:
    kernel, ctx = _make()
    allowed, reason = kernel.pre_execute(ctx, "DROP TABLE users")
    assert allowed is False
    assert reason == "blocked_pattern:DROP TABLE"
    assert ctx.call_count == 0  # blocked calls do not increment


def test_pre_execute_max_tool_calls_cap() -> None:
    kernel, ctx = _make()
    for _ in range(10):
        allowed, _ = kernel.pre_execute(ctx, "ok")
        assert allowed is True
    allowed, reason = kernel.pre_execute(ctx, "ok")
    assert allowed is False
    assert reason == "max_tool_calls exceeded"


def test_evaluate_returns_structured_decision() -> None:
    kernel, ctx = _make()
    decision = kernel.evaluate(ctx, PolicyRequest(payload="Say hello."))
    assert isinstance(decision, PolicyDecision)
    assert decision.allowed is True
    assert decision.reason is None
    assert decision.policy == "t"
    assert decision.payload_hash == hashlib.sha256(b"Say hello.").hexdigest()
    assert ctx.call_count == 1


def test_policy_validation_rejects_negative_max_tool_calls() -> None:
    policy = GovernancePolicy(max_tool_calls=-1)
    with pytest.raises(ValueError, match="max_tool_calls"):
        BaseKernel(policy)


def test_policy_validation_rejects_blank_blocked_pattern() -> None:
    policy = GovernancePolicy(blocked_patterns=["DROP TABLE", " "])
    with pytest.raises(ValueError, match="blocked_patterns"):
        BaseKernel(policy)


def test_policy_validation_rejects_overlapping_tools() -> None:
    policy = GovernancePolicy(
        allowed_tools=["search", "shell_exec"],
        blocked_tools=["shell_exec"],
    )
    with pytest.raises(ValueError, match="both allowed and blocked"):
        BaseKernel(policy)


def test_evaluate_blocks_denied_tool() -> None:
    policy = GovernancePolicy(name="tools", blocked_tools=["shell_exec"])
    kernel = BaseKernel(policy)
    ctx = kernel.create_context("test")
    decision = kernel.evaluate(
        ctx,
        PolicyRequest(payload="ok", tool_name="shell_exec"),
    )
    assert decision.allowed is False
    assert decision.reason == "blocked_tool:shell_exec"
    assert decision.tool_name == "shell_exec"
    assert ctx.call_count == 0


def test_evaluate_blocks_tool_not_in_allowlist() -> None:
    policy = GovernancePolicy(name="tools", allowed_tools=["search"])
    kernel = BaseKernel(policy)
    ctx = kernel.create_context("test")
    decision = kernel.evaluate(
        ctx,
        PolicyRequest(payload="ok", tool_name="shell_exec"),
    )
    assert decision.allowed is False
    assert decision.reason == "tool_not_allowed:shell_exec"
    assert ctx.call_count == 0


def test_evaluate_requires_human_approval() -> None:
    policy = GovernancePolicy(name="approval", require_human_approval=True)
    kernel = BaseKernel(policy)
    ctx = kernel.create_context("test")
    decision = kernel.evaluate(ctx, PolicyRequest(payload="ok"))
    assert decision.allowed is False
    assert decision.reason == "human_approval_required"
    assert decision.requires_approval is True
    assert ctx.call_count == 0


def test_max_calls_checked_before_patterns() -> None:
    policy = GovernancePolicy(blocked_patterns=["DROP TABLE"], max_tool_calls=0)
    kernel = BaseKernel(policy)
    ctx = kernel.create_context("test")
    decision = kernel.evaluate(ctx, PolicyRequest(payload="DROP TABLE users"))
    assert decision.allowed is False
    assert decision.reason == "max_tool_calls exceeded"
    assert decision.matched_pattern is None


def test_audit_records_structured_decision_without_raw_payload() -> None:
    reset_audit()
    kernel, ctx = _make()
    decision = kernel.evaluate(ctx, PolicyRequest(payload="Say hello."))
    audit("test", "pre_execute", "ALLOWED", decision=decision)
    entry = AUDIT[-1]
    assert entry["policy"] == "t"
    assert entry["payload_hash"] == hashlib.sha256(b"Say hello.").hexdigest()
    assert "payload" not in entry
    assert entry["ts"].endswith("+00:00")
    reset_audit()


def test_policy_violation_error_carries_reason() -> None:
    err = PolicyViolationError("blocked", pattern="DROP TABLE")
    assert err.reason == "blocked"
    assert err.pattern == "DROP TABLE"
    assert str(err) == "blocked"


def test_pattern_engine_default_is_substring() -> None:
    p = GovernancePolicy(blocked_patterns=["ssn"])
    assert p.pattern_engine == "substring"
    assert p.matches_pattern("Get user ssn") == "ssn"
    # A regex-style escape is treated as a literal substring under the default
    p_literal = GovernancePolicy(blocked_patterns=[r"\bssn\b"])
    assert p_literal.matches_pattern("Get user ssn") is None


def test_pattern_engine_regex_matches_word_boundary() -> None:
    p = GovernancePolicy(blocked_patterns=[r"\bssn\b"], pattern_engine="regex")
    assert p.matches_pattern("Get user ssn now") == r"\bssn\b"
    assert p.matches_pattern("get user assness today") is None  # no word boundary


def test_pattern_engine_regex_is_case_insensitive() -> None:
    p = GovernancePolicy(blocked_patterns=[r"DROP\s+TABLE"], pattern_engine="regex")
    assert p.matches_pattern("please drop\ttable users") == r"DROP\s+TABLE"


def test_pattern_engine_invalid_value_rejected() -> None:
    policy = GovernancePolicy(blocked_patterns=["x"], pattern_engine="fuzzy")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="pattern_engine"):
        BaseKernel(policy)


def test_pattern_engine_regex_validates_at_construction() -> None:
    policy = GovernancePolicy(
        blocked_patterns=["[unclosed"], pattern_engine="regex"
    )
    with pytest.raises(ValueError, match="invalid regex"):
        BaseKernel(policy)


def test_audit_payload_summary_field_validates_non_negative() -> None:
    policy = GovernancePolicy(audit_payload_summary=-1)
    with pytest.raises(ValueError, match="audit_payload_summary"):
        BaseKernel(policy)


def test_audit_records_payload_summary_when_provided() -> None:
    reset_audit()
    audit(
        "test",
        "phase",
        "ALLOWED",
        payload_hash="abc",
        payload_summary="hello world",
    )
    entry = AUDIT[-1]
    assert entry["payload_summary"] == "hello world"
    assert entry["payload_hash"] == "abc"
    reset_audit()


def test_audit_omits_payload_summary_when_not_set() -> None:
    reset_audit()
    audit("test", "phase", "ALLOWED", payload_hash="abc")
    entry = AUDIT[-1]
    assert "payload_summary" not in entry
    reset_audit()


def test_claude_hook_blocks_with_core_decision() -> None:
    from policy_engine.adapters.claude import make_user_prompt_hook

    reset_audit()
    hook = make_user_prompt_hook(
        GovernancePolicy(blocked_patterns=["DROP TABLE"])
    )
    result = asyncio.run(hook({"prompt": "DROP TABLE users"}, None, None))
    output = result["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert output["permissionDecisionReason"] == "Blocked pattern: DROP TABLE"
    assert AUDIT[-1]["reason"] == "blocked_pattern:DROP TABLE"
    assert "payload_hash" in AUDIT[-1]
    reset_audit()


def test_maf_policy_middleware_blocks_tool() -> None:
    from policy_engine.adapters.maf import create_governance_middleware

    class FunctionCall:
        name = "shell_exec"

    class Context:
        function_call = FunctionCall()

    async def next_(context):
        return "ok"

    stack = create_governance_middleware(
        policy=GovernancePolicy(blocked_tools=["shell_exec"])
    )
    assert len(stack) == 1
    with pytest.raises(PermissionError, match="blocked_tool:shell_exec"):
        asyncio.run(stack[0](Context(), next_))


def test_maf_legacy_empty_configuration_stays_noop() -> None:
    from policy_engine.adapters.maf import create_governance_middleware

    assert create_governance_middleware() == []


def test_agent_os_kernel_blocks_pattern_with_local_decision_shape() -> None:
    from policy_engine.adapters.agent_os import AgentOSKernel, AgentOSUnavailableError

    policy = GovernancePolicy(
        name="agent-os-test",
        blocked_patterns=["DROP TABLE"],
    )
    kernel = AgentOSKernel(policy)
    ctx = kernel.create_context("test")
    try:
        decision = kernel.evaluate(ctx, PolicyRequest(payload="DROP TABLE users"))
    except AgentOSUnavailableError as exc:
        pytest.skip(str(exc))

    assert decision.allowed is False
    assert decision.reason == "blocked_pattern:DROP TABLE"
    assert decision.matched_pattern == "DROP TABLE"
    assert decision.policy == "agent-os-test"
    assert ctx.call_count == 0


def test_agent_os_kernel_enforces_local_blocked_tools_before_backend() -> None:
    from policy_engine.adapters.agent_os import AgentOSKernel

    policy = GovernancePolicy(name="agent-os-tools", blocked_tools=["shell_exec"])
    kernel = AgentOSKernel(policy)
    ctx = kernel.create_context("test")
    decision = kernel.evaluate(
        ctx,
        PolicyRequest(payload="ok", tool_name="shell_exec"),
    )

    assert decision.allowed is False
    assert decision.reason == "blocked_tool:shell_exec"
    assert ctx.call_count == 0


def test_agent_os_kernel_preserves_pre_execute_compatibility() -> None:
    from policy_engine.adapters.agent_os import AgentOSKernel, AgentOSUnavailableError

    kernel = AgentOSKernel(GovernancePolicy(name="agent-os-compat"))
    ctx = kernel.create_context("test")
    try:
        allowed, reason = kernel.pre_execute(ctx, "Say hello.")
    except AgentOSUnavailableError as exc:
        pytest.skip(str(exc))

    assert allowed is True
    assert reason is None
    assert ctx.call_count == 1
