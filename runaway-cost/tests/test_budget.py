from __future__ import annotations

import pytest

from runaway_cost import BudgetPolicy, BudgetTracker, TokenBudgetTracker


def test_budget_policy_validation():
    with pytest.raises(ValueError):
        BudgetPolicy(max_tokens=-1)
    with pytest.raises(ValueError):
        BudgetPolicy(max_cost_usd=-0.01)
    with pytest.raises(ValueError):
        BudgetPolicy(warning_threshold=1.1)


def test_budget_tracker_records_remaining_utilization_and_exceeded_reasons():
    tracker = BudgetTracker(
        BudgetPolicy(
            max_tokens=10,
            max_tool_calls=1,
            max_cost_usd=0.10,
            max_duration_seconds=2.0,
            max_retries=1,
            warning_threshold=0.8,
        )
    )

    tracker.record_tokens(8)
    tracker.record_tool_call()
    tracker.record_cost(0.08)
    tracker.record_duration(1.0)
    tracker.record_retry()

    status = tracker.status()
    assert status.warning
    assert not status.exceeded
    assert status.remaining["tokens"] == 2
    assert status.utilization["cost_usd"] == 0.8

    projected = tracker.would_exceed(tokens=3, tool_calls=1, cost_usd=0.03, duration_seconds=2.0, retries=1)
    assert "tokens: 11/10" in projected
    assert "tool_calls: 2/1" in projected
    assert "cost_usd: 0.1100/0.1000" in projected
    assert "duration_seconds: 3.00/2.00" in projected
    assert "retries: 2/1" in projected

    tracker.record_tokens(3)
    assert tracker.is_exceeded()


def test_budget_tracker_rejects_negative_records():
    tracker = BudgetTracker(BudgetPolicy(max_tokens=10))
    with pytest.raises(ValueError):
        tracker.record_tokens(-1)
    with pytest.raises(ValueError):
        tracker.record_tool_call(-1)
    with pytest.raises(ValueError):
        tracker.record_cost(-0.01)
    with pytest.raises(ValueError):
        tracker.record_duration(-1)
    with pytest.raises(ValueError):
        tracker.record_retry(-1)


def test_token_budget_tracker_warning_once_exceeded_reset_and_format():
    warnings = []
    tracker = TokenBudgetTracker(
        max_tokens=10,
        warning_threshold=0.5,
        on_warning=lambda agent_id, status: warnings.append((agent_id, status)),
    )

    status = tracker.record_usage("agent-1", prompt_tokens=3, completion_tokens=2)
    assert status.is_warning
    assert not status.is_exceeded
    assert len(warnings) == 1

    status = tracker.record_usage("agent-1", prompt_tokens=2, completion_tokens=3)
    assert status.is_exceeded
    assert len(warnings) == 1
    assert tracker.check_budget("agent-1").used == 10
    assert "10/10 tokens" in tracker.format_status("agent-1")

    tracker.reset("agent-1")
    assert tracker.get_usage("agent-1").used == 0
