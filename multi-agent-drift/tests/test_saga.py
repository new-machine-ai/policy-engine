import asyncio

import pytest

from multi_agent_drift import (
    FanOutOrchestrator,
    FanOutPolicy,
    SagaOrchestrator,
    SagaState,
    SagaStep,
    StepState,
)


def test_saga_step_retry_and_compensation_order():
    async def run():
        orchestrator = SagaOrchestrator()
        saga = orchestrator.create_saga("session-1")
        first = orchestrator.add_step(
            saga.saga_id,
            "reserve-a",
            "agent-a",
            "reserve",
            "release",
            max_retries=1,
        )
        second = orchestrator.add_step(
            saga.saga_id,
            "reserve-b",
            "agent-b",
            "reserve",
            "release",
        )
        attempts = {"count": 0}

        def flaky():
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("temporary")
            return "ok-a"

        assert await orchestrator.execute_step(saga.saga_id, first.step_id, flaky) == "ok-a"
        assert await orchestrator.execute_step(saga.saga_id, second.step_id, lambda: "ok-b") == "ok-b"
        assert first.retry_count == 1
        assert first.state == StepState.COMMITTED
        assert second.state == StepState.COMMITTED

        compensated = []

        def compensate(step):
            compensated.append(step.action_id)
            return f"undo-{step.action_id}"

        failed = await orchestrator.compensate(saga.saga_id, compensate)

        assert failed == []
        assert compensated == ["reserve-b", "reserve-a"]
        assert saga.state == SagaState.COMPLETED
        assert first.state == StepState.COMPENSATED
        assert second.state == StepState.COMPENSATED

    asyncio.run(run())


def test_fanout_policies_and_compensation_markers():
    async def run(policy, outcomes):
        fanout = FanOutOrchestrator()
        group = fanout.create_group("saga-1", policy)
        steps = [
            SagaStep(
                step_id=f"step-{index}",
                action_id=f"branch-{index}",
                agent_did=f"agent-{index}",
                execute_api="do",
                undo_api="undo",
                timeout_seconds=1,
            )
            for index in range(len(outcomes))
        ]
        for step in steps:
            fanout.add_branch(group.group_id, step)

        def executor(outcome):
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        executors = {
            step.step_id: (lambda outcome=outcome: executor(outcome))
            for step, outcome in zip(steps, outcomes)
        }
        return await fanout.execute(group.group_id, executors, timeout_seconds=1)

    all_group = asyncio.run(run(FanOutPolicy.ALL_MUST_SUCCEED, ["a", RuntimeError("boom")]))
    majority_group = asyncio.run(run(FanOutPolicy.MAJORITY_MUST_SUCCEED, ["a", "b", RuntimeError("boom")]))
    any_group = asyncio.run(run(FanOutPolicy.ANY_MUST_SUCCEED, [RuntimeError("boom"), "b"]))

    assert all_group.resolved is True
    assert all_group.policy_satisfied is False
    assert len(all_group.compensation_needed) == 1

    assert majority_group.policy_satisfied is True
    assert majority_group.success_count == 2
    assert majority_group.failure_count == 1

    assert any_group.policy_satisfied is True


def test_saga_compensation_escalates_when_undo_is_missing():
    async def run():
        orchestrator = SagaOrchestrator()
        saga = orchestrator.create_saga("session-1")
        step = orchestrator.add_step(saga.saga_id, "commit", "agent-a", "do")
        await orchestrator.execute_step(saga.saga_id, step.step_id, lambda: "ok")
        failed = await orchestrator.compensate(saga.saga_id, lambda _step: "unused")
        return saga, failed

    saga, failed = asyncio.run(run())

    assert saga.state == SagaState.ESCALATED
    assert len(failed) == 1
    assert failed[0].state == StepState.COMPENSATION_FAILED


def test_saga_step_timeout_raises():
    async def run():
        orchestrator = SagaOrchestrator()
        saga = orchestrator.create_saga("session-1")
        step = orchestrator.add_step(
            saga.saga_id,
            "slow",
            "agent-a",
            "do",
            timeout_seconds=0.001,
        )

        async def slow():
            await asyncio.sleep(0.01)

        with pytest.raises(Exception):
            await orchestrator.execute_step(saga.saga_id, step.step_id, slow)

    asyncio.run(run())
