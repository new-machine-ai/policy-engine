# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""SIGSTOP and SIGKILL kill-switch example."""

from __future__ import annotations

from human_loop import KillReason, KillSignal, KillSwitch


def main() -> None:
    killed = []
    switch = KillSwitch()
    switch.register_agent("agent-1", lambda: killed.append("agent-1"))
    print(switch.kill("agent-1", "session-1", KillReason.MANUAL, signal=KillSignal.SIGSTOP).to_dict())
    print({"stopped": switch.is_stopped("agent-1")})
    switch.register_substitute("session-1", "agent-2")
    print(
        switch.kill(
            "agent-1",
            "session-1",
            KillReason.MANUAL,
            signal=KillSignal.SIGKILL,
            in_flight_steps=[{"step_id": "step-1", "saga_id": "saga-1"}],
        ).to_dict()
    )
    print({"terminated_callbacks": killed})


if __name__ == "__main__":
    main()
