import pytest

from multi_agent_drift import AgentSignal, BudgetExceeded, ContextPriority, ContextScheduler


def test_context_allocation_usage_thresholds_release_and_signals():
    scheduler = ContextScheduler(total_budget=100, warn_threshold=0.5)
    signals = []
    for signal in AgentSignal:
        scheduler.on_signal(signal, lambda agent_id, emitted: signals.append((agent_id, emitted)))

    window = scheduler.allocate("planner", "review", ContextPriority.HIGH, max_tokens=100)

    assert window.total == 100
    assert scheduler.active_count == 1
    assert scheduler.available_tokens == 0
    assert signals == [("planner", AgentSignal.SIGRESUME)]

    record = scheduler.record_usage("planner", lookup_tokens=40, reasoning_tokens=10)

    assert record.total_used == 50
    assert ("planner", AgentSignal.SIGWARN) in signals

    scheduler.record_usage("planner", lookup_tokens=49)
    with pytest.raises(BudgetExceeded):
        scheduler.record_usage("planner", lookup_tokens=1)

    assert ("planner", AgentSignal.SIGSTOP) in signals
    released = scheduler.release("planner")
    assert released is not None
    assert released.stopped is True
    assert scheduler.active_count == 0
    assert scheduler.available_tokens == 100
    assert scheduler.get_health_report()["history_count"] == 1


def test_context_scheduler_rejects_invalid_usage():
    scheduler = ContextScheduler(total_budget=100)
    scheduler.allocate("agent-a", "task", max_tokens=50)

    with pytest.raises(ValueError):
        scheduler.record_usage("agent-a", lookup_tokens=-1)

    with pytest.raises(KeyError):
        scheduler.record_usage("missing", lookup_tokens=1)
