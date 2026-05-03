import pytest

from multi_agent_drift import (
    CausalViolationError,
    IntentLockManager,
    LockContentionError,
    LockIntent,
    VectorClock,
    VectorClockManager,
)


def test_intent_locks_enforce_contention_and_cleanup():
    manager = IntentLockManager()

    read_a = manager.acquire("agent-a", "session-1", "/orders/1", LockIntent.READ)
    read_b = manager.acquire("agent-b", "session-1", "/orders/1", LockIntent.READ)
    assert manager.active_lock_count == 2
    assert manager.contention_points == ["/orders/1"]

    with pytest.raises(LockContentionError):
        manager.acquire("agent-c", "session-1", "/orders/1", LockIntent.WRITE)

    manager.release(read_a.lock_id)
    manager.release(read_b.lock_id)
    write = manager.acquire("agent-c", "session-1", "/orders/1", LockIntent.WRITE)

    with pytest.raises(LockContentionError):
        manager.acquire("agent-d", "session-1", "/orders/1", LockIntent.READ)

    released = manager.release_session_locks("session-1")
    assert released == 1
    assert write.is_active is False
    assert manager.active_lock_count == 0


def test_vector_clocks_ordering_concurrency_and_causal_write_checks():
    clock_a = VectorClock()
    clock_a.tick("agent-a")
    clock_b = clock_a.copy()
    clock_b.tick("agent-b")
    clock_c = VectorClock()
    clock_c.tick("agent-c")

    assert clock_a.happens_before(clock_b)
    assert not clock_b.happens_before(clock_a)
    assert clock_a.is_concurrent(clock_c)
    assert not clock_a.is_concurrent(clock_a)
    assert clock_a.merge(clock_c).clocks == {"agent-a": 1, "agent-c": 1}

    manager = VectorClockManager()
    manager.write("/orders/1", "agent-a")
    with pytest.raises(CausalViolationError):
        manager.write("/orders/1", "agent-b")

    manager.read("/orders/1", "agent-b")
    written = manager.write("/orders/1", "agent-b")

    assert written.get("agent-a") == 1
    assert written.get("agent-b") == 1
    assert manager.conflict_count == 1
