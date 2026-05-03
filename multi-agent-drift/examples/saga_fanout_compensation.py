# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Saga fan-out with compensation after a branch failure."""

from __future__ import annotations

import asyncio

from multi_agent_drift import FanOutOrchestrator, FanOutPolicy, SagaOrchestrator


async def main() -> None:
    sagas = SagaOrchestrator()
    saga = sagas.create_saga("session-1")
    reserve_inventory = sagas.add_step(
        saga.saga_id,
        "reserve-inventory",
        "inventory-agent",
        "reserve",
        "release",
    )
    reserve_payment = sagas.add_step(
        saga.saga_id,
        "reserve-payment",
        "payment-agent",
        "reserve",
        "release",
    )

    fanout = FanOutOrchestrator()
    group = fanout.create_group(saga.saga_id, FanOutPolicy.ALL_MUST_SUCCEED)
    fanout.add_branch(group.group_id, reserve_inventory)
    fanout.add_branch(group.group_id, reserve_payment)

    def fail_payment():
        raise RuntimeError("payment provider unavailable")

    result = await fanout.execute(
        group.group_id,
        {
            reserve_inventory.step_id: lambda: "inventory-held",
            reserve_payment.step_id: fail_payment,
        },
    )
    print(f"policy_satisfied={result.policy_satisfied}")
    print(f"compensation_needed={result.compensation_needed}")

    if result.compensation_needed:
        failed = await sagas.compensate(saga.saga_id, lambda step: f"undo-{step.action_id}")
        print(f"saga_state={saga.state.value} compensation_failures={len(failed)}")


if __name__ == "__main__":
    asyncio.run(main())
