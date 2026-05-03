from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from runaway_cost import (
    AgentRateLimiter,
    BudgetPolicy,
    CircuitBreakerConfig,
    ExecutionRing,
    RunawayCostGuard,
    SlidingWindowRateLimiter,
)


ROOT = Path(__file__).resolve().parents[1]


def test_guard_blocks_open_circuit_before_budget_and_rate_checks():
    guard = RunawayCostGuard(
        budget_policy=BudgetPolicy(max_tokens=0),
        circuit_config=CircuitBreakerConfig(failure_threshold=1),
    )
    guard.record_failure("agent-1", "session-1")

    decision = guard.evaluate_attempt(
        "agent-1",
        "session-1",
        "call_model",
        estimated_tokens=10,
    )

    assert not decision.allowed
    assert decision.reason == "circuit open"
    assert decision.circuit_state.value == "open"


def test_guard_blocks_rate_limit_then_budget_and_records_usage():
    rate_limiter = AgentRateLimiter(
        ring_limits={ExecutionRing.RING_2_STANDARD: (0.0, 1.0)}
    )
    guard = RunawayCostGuard(
        budget_policy=BudgetPolicy(max_tokens=10, max_tool_calls=10, max_cost_usd=1.0, max_retries=10),
        agent_rate_limiter=rate_limiter,
        sliding_limiter=SlidingWindowRateLimiter(max_calls_per_window=10, window_size=60),
    )

    assert guard.evaluate_attempt("agent-1", "session-1", "call_model").allowed
    rate_denied = guard.evaluate_attempt("agent-1", "session-1", "call_model")
    assert not rate_denied.allowed
    assert "exceeded rate limit" in rate_denied.reason

    budget_guard = RunawayCostGuard(
        budget_policy=BudgetPolicy(max_tokens=10, max_tool_calls=10, max_cost_usd=1.0, max_retries=10),
        agent_rate_limiter=AgentRateLimiter(
            ring_limits={ExecutionRing.RING_2_STANDARD: (100.0, 100.0)}
        ),
        sliding_limiter=SlidingWindowRateLimiter(max_calls_per_window=10, window_size=60),
    )
    budget_denied = budget_guard.evaluate_attempt(
        "agent-1",
        "session-1",
        "call_model",
        estimated_tokens=11,
    )
    assert not budget_denied.allowed
    assert budget_denied.reason.startswith("budget would be exceeded")

    allowed = budget_guard.evaluate_attempt("agent-1", "session-1", "call_model", estimated_tokens=5)
    assert allowed.allowed
    status = budget_guard.record_success("agent-1", "session-1", tokens=5, cost_usd=0.1)
    assert status.remaining["tokens"] == 5
    budget_guard.record_failure("agent-1", "session-1")
    report = budget_guard.report()
    assert "agent-1:session-1" in report["budgets"]
    assert report["circuits"]["agent-1"]["failure_count"] == 1


def test_cli_check_json_allowed():
    result = _run_cli(
        "check",
        "--agent-id",
        "agent-1",
        "--session-id",
        "session-1",
        "--operation",
        "call_model",
        "--tokens",
        "100",
        "--cost-usd",
        "0.01",
        "--format",
        "json",
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["allowed"] is True
    assert payload["metadata_hash"]


def test_cli_nonzero_for_budget_rate_and_circuit_denials():
    budget = _run_cli(
        "budget",
        "record",
        "--agent-id",
        "agent-1",
        "--tokens",
        "11",
        "--max-tokens",
        "10",
        "--format",
        "json",
    )
    assert budget.returncode == 1
    assert json.loads(budget.stdout)["budget"]["exceeded"] is True

    rate = _run_cli(
        "rate-limit",
        "acquire",
        "--agent-id",
        "agent-1",
        "--limit",
        "1",
        "--attempts",
        "2",
        "--format",
        "json",
    )
    assert rate.returncode == 1
    assert json.loads(rate.stdout)["allowed"] is False

    circuit = _run_cli(
        "circuit",
        "fail",
        "--agent-id",
        "agent-1",
        "--threshold",
        "1",
        "--format",
        "json",
    )
    assert circuit.returncode == 1
    assert json.loads(circuit.stdout)["state"] == "open"


def test_cli_retry_simulation_and_markdown_report():
    retry_result = _run_cli(
        "simulate-retries",
        "--max-attempts",
        "3",
        "--failures",
        "5",
        "--format",
        "json",
    )
    assert retry_result.returncode == 0
    payload = json.loads(retry_result.stdout)
    assert payload["exhausted"] is True
    assert payload["attempts"] == 3

    report = _run_cli("report", "--format", "markdown")
    assert report.returncode == 0
    assert "# Runaway Cost Report" in report.stdout


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    package_src = str(ROOT / "src")
    env["PYTHONPATH"] = package_src + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "runaway_cost.cli", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
