from human_loop import HandoffStatus, KillReason, KillSignal, KillSwitch


def test_sigstop_blocks_without_termination_and_resume():
    calls = []
    switch = KillSwitch()
    switch.register_agent("agent-a", lambda: calls.append("terminated"))

    result = switch.kill("agent-a", "session-1", KillReason.MANUAL, signal=KillSignal.SIGSTOP)

    assert result.stopped
    assert not result.terminated
    assert calls == []
    assert switch.is_stopped("agent-a")
    assert switch.resume_agent("agent-a")
    assert not switch.is_stopped("agent-a")


def test_sigkill_terminates_and_hands_off_or_compensates():
    calls = []
    switch = KillSwitch()
    switch.register_agent("agent-a", lambda: calls.append("terminated"))
    switch.register_substitute("session-1", "agent-b")

    handed_off = switch.kill(
        "agent-a",
        "session-1",
        KillReason.MANUAL,
        signal=KillSignal.SIGKILL,
        in_flight_steps=[{"step_id": "step-1", "saga_id": "saga-1"}],
    )

    assert calls == ["terminated"]
    assert handed_off.terminated
    assert handed_off.handoffs[0].status == HandoffStatus.HANDED_OFF
    assert handed_off.handoffs[0].to_agent == "agent-b"
    assert switch.total_handoffs == 1

    compensated = switch.kill(
        "agent-c",
        "session-2",
        KillReason.RATE_LIMIT,
        signal=KillSignal.SIGKILL,
        in_flight_steps=[{"step_id": "step-2", "saga_id": "saga-1"}],
    )

    assert compensated.handoffs[0].status == HandoffStatus.COMPENSATED
    assert compensated.compensation_triggered
    assert switch.total_kills == 2
