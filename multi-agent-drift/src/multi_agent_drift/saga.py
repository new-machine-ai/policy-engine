# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Saga and fan-out orchestration for multi-agent handoffs."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

SAGA_DEFAULT_MAX_RETRIES = 2
SAGA_DEFAULT_RETRY_DELAY_SECONDS = 0.01
SAGA_DEFAULT_STEP_TIMEOUT_SECONDS = 300


class StepState(str, Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMMITTED = "committed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    COMPENSATION_FAILED = "compensation_failed"
    FAILED = "failed"


class SagaState(str, Enum):
    RUNNING = "running"
    COMPENSATING = "compensating"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"


STEP_TRANSITIONS: dict[StepState, set[StepState]] = {
    StepState.PENDING: {StepState.EXECUTING},
    StepState.EXECUTING: {StepState.COMMITTED, StepState.FAILED},
    StepState.COMMITTED: {StepState.COMPENSATING},
    StepState.COMPENSATING: {StepState.COMPENSATED, StepState.COMPENSATION_FAILED},
    StepState.COMPENSATED: set(),
    StepState.COMPENSATION_FAILED: set(),
    StepState.FAILED: set(),
}

SAGA_TRANSITIONS: dict[SagaState, set[SagaState]] = {
    SagaState.RUNNING: {SagaState.COMPENSATING, SagaState.COMPLETED, SagaState.FAILED},
    SagaState.COMPENSATING: {SagaState.COMPLETED, SagaState.FAILED, SagaState.ESCALATED},
    SagaState.COMPLETED: set(),
    SagaState.FAILED: set(),
    SagaState.ESCALATED: set(),
}


class SagaStateError(Exception):
    """Raised for invalid saga state transitions."""


class SagaTimeoutError(Exception):
    """Raised when a saga step exceeds its timeout."""


@dataclass
class SagaStep:
    """A single step in a saga."""

    step_id: str
    action_id: str
    agent_did: str
    execute_api: str
    undo_api: str | None = None
    state: StepState = StepState.PENDING
    execute_result: Any | None = None
    compensation_result: Any | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    timeout_seconds: float = SAGA_DEFAULT_STEP_TIMEOUT_SECONDS
    max_retries: int = 0
    retry_count: int = 0

    def transition(self, new_state: StepState) -> None:
        allowed = STEP_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise SagaStateError(f"Invalid step transition: {self.state.value} -> {new_state.value}")
        self.state = new_state
        now = datetime.now(UTC)
        if new_state == StepState.EXECUTING:
            self.started_at = now
        if new_state in {
            StepState.COMMITTED,
            StepState.COMPENSATED,
            StepState.COMPENSATION_FAILED,
            StepState.FAILED,
        }:
            self.completed_at = now


@dataclass
class Saga:
    """A saga consisting of ordered steps."""

    saga_id: str
    session_id: str
    steps: list[SagaStep] = field(default_factory=list)
    state: SagaState = SagaState.RUNNING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    error: str | None = None

    def transition(self, new_state: SagaState) -> None:
        allowed = SAGA_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise SagaStateError(f"Invalid saga transition: {self.state.value} -> {new_state.value}")
        self.state = new_state
        if new_state in (SagaState.COMPLETED, SagaState.FAILED, SagaState.ESCALATED):
            self.completed_at = datetime.now(UTC)

    @property
    def committed_steps(self) -> list[SagaStep]:
        return [step for step in self.steps if step.state == StepState.COMMITTED]

    @property
    def committed_steps_reversed(self) -> list[SagaStep]:
        return list(reversed(self.committed_steps))


class SagaOrchestrator:
    """Orchestrates multi-step transactions with saga compensation."""

    DEFAULT_MAX_RETRIES = SAGA_DEFAULT_MAX_RETRIES
    DEFAULT_RETRY_DELAY_SECONDS = SAGA_DEFAULT_RETRY_DELAY_SECONDS

    def __init__(self) -> None:
        self._sagas: dict[str, Saga] = {}

    def create_saga(self, session_id: str) -> Saga:
        saga = Saga(saga_id=f"saga:{uuid.uuid4()}", session_id=session_id)
        self._sagas[saga.saga_id] = saga
        return saga

    def add_step(
        self,
        saga_id: str,
        action_id: str,
        agent_did: str,
        execute_api: str,
        undo_api: str | None = None,
        timeout_seconds: float = SAGA_DEFAULT_STEP_TIMEOUT_SECONDS,
        max_retries: int = 0,
    ) -> SagaStep:
        saga = self._get_saga(saga_id)
        step = SagaStep(
            step_id=f"step:{uuid.uuid4()}",
            action_id=action_id,
            agent_did=agent_did,
            execute_api=execute_api,
            undo_api=undo_api,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        saga.steps.append(step)
        return step

    async def execute_step(self, saga_id: str, step_id: str, executor: Callable[..., Any]) -> Any:
        saga = self._get_saga(saga_id)
        step = self._get_step(saga, step_id)
        last_error: Exception | None = None
        for attempt in range(1 + step.max_retries):
            step.retry_count = attempt
            step.transition(StepState.EXECUTING)
            try:
                result = await asyncio.wait_for(_maybe_await(executor()), timeout=step.timeout_seconds)
                step.execute_result = result
                step.transition(StepState.COMMITTED)
                return result
            except TimeoutError:
                last_error = SagaTimeoutError(f"Step {step_id} timed out after {step.timeout_seconds}s")
            except Exception as exc:
                last_error = exc
            step.error = str(last_error)
            step.transition(StepState.FAILED)
            if attempt < step.max_retries:
                step.state = StepState.PENDING
                step.error = None
                await asyncio.sleep(self.DEFAULT_RETRY_DELAY_SECONDS * (attempt + 1))
        raise last_error or SagaStateError("Step execution failed with no error captured")

    async def compensate(self, saga_id: str, compensator: Callable[[SagaStep], Any]) -> list[SagaStep]:
        saga = self._get_saga(saga_id)
        saga.transition(SagaState.COMPENSATING)
        failed: list[SagaStep] = []
        for step in saga.committed_steps_reversed:
            if not step.undo_api:
                step.state = StepState.COMPENSATION_FAILED
                step.error = "No Undo_API available"
                failed.append(step)
                continue
            step.transition(StepState.COMPENSATING)
            try:
                result = await asyncio.wait_for(_maybe_await(compensator(step)), timeout=step.timeout_seconds)
                step.compensation_result = result
                step.transition(StepState.COMPENSATED)
            except Exception as exc:
                step.error = f"Compensation failed: {exc}"
                step.transition(StepState.COMPENSATION_FAILED)
                failed.append(step)
        if failed:
            saga.error = f"{len(failed)} step(s) failed compensation"
            saga.transition(SagaState.ESCALATED)
        else:
            saga.transition(SagaState.COMPLETED)
        return failed

    def get_saga(self, saga_id: str) -> Saga | None:
        return self._sagas.get(saga_id)

    @property
    def active_sagas(self) -> list[Saga]:
        return [saga for saga in self._sagas.values() if saga.state in (SagaState.RUNNING, SagaState.COMPENSATING)]

    def _get_saga(self, saga_id: str) -> Saga:
        saga = self._sagas.get(saga_id)
        if saga is None:
            raise SagaStateError(f"Saga {saga_id} not found")
        return saga

    @staticmethod
    def _get_step(saga: Saga, step_id: str) -> SagaStep:
        for step in saga.steps:
            if step.step_id == step_id:
                return step
        raise SagaStateError(f"Step {step_id} not found in saga {saga.saga_id}")


class FanOutPolicy(str, Enum):
    ALL_MUST_SUCCEED = "all_must_succeed"
    MAJORITY_MUST_SUCCEED = "majority_must_succeed"
    ANY_MUST_SUCCEED = "any_must_succeed"


@dataclass
class FanOutBranch:
    branch_id: str = field(default_factory=lambda: f"branch:{uuid.uuid4().hex[:8]}")
    step: SagaStep | None = None
    result: Any = None
    error: str | None = None
    succeeded: bool = False


@dataclass
class FanOutGroup:
    group_id: str = field(default_factory=lambda: f"fanout:{uuid.uuid4().hex[:8]}")
    saga_id: str = ""
    policy: FanOutPolicy = FanOutPolicy.ALL_MUST_SUCCEED
    branches: list[FanOutBranch] = field(default_factory=list)
    resolved: bool = False
    policy_satisfied: bool = False
    compensation_needed: list[str] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum(1 for branch in self.branches if branch.succeeded)

    @property
    def failure_count(self) -> int:
        return sum(1 for branch in self.branches if branch.error)

    @property
    def total_branches(self) -> int:
        return len(self.branches)

    def check_policy(self) -> bool:
        if self.total_branches == 0:
            return False
        if self.policy == FanOutPolicy.ALL_MUST_SUCCEED:
            return self.success_count == self.total_branches
        if self.policy == FanOutPolicy.MAJORITY_MUST_SUCCEED:
            return self.success_count > self.total_branches // 2
        return self.success_count >= 1


class FanOutOrchestrator:
    """Execute saga branches and resolve configurable fan-out policies."""

    def __init__(self) -> None:
        self._groups: dict[str, FanOutGroup] = {}

    def create_group(self, saga_id: str, policy: FanOutPolicy = FanOutPolicy.ALL_MUST_SUCCEED) -> FanOutGroup:
        group = FanOutGroup(saga_id=saga_id, policy=policy)
        self._groups[group.group_id] = group
        return group

    def add_branch(self, group_id: str, step: SagaStep) -> FanOutBranch:
        group = self._get_group(group_id)
        branch = FanOutBranch(step=step)
        group.branches.append(branch)
        return branch

    async def execute(self, group_id: str, executors: dict[str, Callable[..., Any]], timeout_seconds: float = 300) -> FanOutGroup:
        group = self._get_group(group_id)
        await asyncio.wait_for(
            asyncio.gather(*(self._execute_branch(branch, executors) for branch in group.branches)),
            timeout=timeout_seconds,
        )
        group.policy_satisfied = group.check_policy()
        group.resolved = True
        if not group.policy_satisfied:
            group.compensation_needed = [
                branch.step.step_id for branch in group.branches if branch.succeeded and branch.step is not None
            ]
        return group

    def get_group(self, group_id: str) -> FanOutGroup | None:
        return self._groups.get(group_id)

    @property
    def active_groups(self) -> list[FanOutGroup]:
        return [group for group in self._groups.values() if not group.resolved]

    async def _execute_branch(self, branch: FanOutBranch, executors: dict[str, Callable[..., Any]]) -> None:
        if branch.step is None:
            branch.error = "No step assigned"
            return
        executor = executors.get(branch.step.step_id)
        if executor is None:
            branch.error = f"No executor for step {branch.step.step_id}"
            return
        try:
            branch.step.transition(StepState.EXECUTING)
            result = await asyncio.wait_for(_maybe_await(executor()), timeout=branch.step.timeout_seconds)
            branch.result = result
            branch.succeeded = True
            branch.step.execute_result = result
            branch.step.transition(StepState.COMMITTED)
        except Exception as exc:
            branch.error = str(exc)
            branch.step.error = str(exc)
            if branch.step.state == StepState.EXECUTING:
                branch.step.transition(StepState.FAILED)

    def _get_group(self, group_id: str) -> FanOutGroup:
        group = self._groups.get(group_id)
        if group is None:
            raise ValueError(f"Fan-out group {group_id} not found")
        return group


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value

