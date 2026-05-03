import json

from human_loop import (
    EscalationDecision,
    HumanLoopGuard,
    KillReason,
    KillSignal,
    Role,
)
from human_loop.cli import main


def test_guard_decision_ordering_and_irreversible_escalation():
    guard = HumanLoopGuard()
    guard.rbac.assign_role("agent-a", Role.ADMIN)
    guard.kill_switch.kill("agent-a", "session-1", KillReason.MANUAL, signal=KillSignal.SIGSTOP)

    stopped = guard.evaluate_action("agent-a", "session-1", "deploy")

    assert not stopped.allowed
    assert stopped.decision == EscalationDecision.DENY
    assert "stopped" in stopped.reason

    guard.kill_switch.resume_agent("agent-a")
    reader_denied = guard.evaluate_action("reader", "session-1", "deploy")
    assert reader_denied.decision == EscalationDecision.DENY
    assert "lacks permission" in reader_denied.reason

    escalated = guard.evaluate_action("agent-a", "session-1", "deploy")
    assert escalated.decision == EscalationDecision.PENDING
    assert escalated.request is not None
    assert guard.escalation.approve(escalated.request.request_id, "approver")
    assert guard.escalation.resolve(escalated.request.request_id) == EscalationDecision.ALLOW


def test_guard_allows_permitted_reversible_action_with_custom_permission():
    guard = HumanLoopGuard()
    guard.rbac.assign_role("agent-a", Role.WRITER)
    guard.rbac.set_permissions(Role.WRITER, {"write_file"})

    decision = guard.evaluate_action("agent-a", "session-1", "write_file")

    assert decision.allowed
    assert decision.decision == EscalationDecision.ALLOW


def test_cli_classify_and_check_action(capsys):
    classify_exit = main(["classify", "--action", "deploy", "--format", "json"])
    classify_output = json.loads(capsys.readouterr().out)

    check_exit = main(
        [
            "check-action",
            "--agent-id",
            "agent-1",
            "--session-id",
            "session-1",
            "--action",
            "deploy",
            "--role",
            "admin",
            "--format",
            "json",
        ]
    )
    check_output = json.loads(capsys.readouterr().out)

    assert classify_exit == 0
    assert classify_output["level"] == "irreversible"
    assert check_exit == 1
    assert check_output["decision"] == "pending"


def test_cli_approval_state_kill_and_registry(tmp_path, capsys):
    state = tmp_path / "approvals.json"
    assert main(["request-approval", "--agent-id", "agent-1", "--action", "deploy", "--state-file", str(state)]) == 0
    request = json.loads(capsys.readouterr().out)
    assert main(["approve", request["request_id"], "--approver", "alice", "--state-file", str(state)]) == 0
    assert json.loads(capsys.readouterr().out)["accepted"] is True

    assert main(["kill", "--agent-id", "agent-1", "--session-id", "session-1", "--signal", "sigstop", "--reason", "manual", "--format", "json"]) == 1
    assert json.loads(capsys.readouterr().out)["stopped"] is True

    assert main(["registry", "report", "--format", "markdown"]) == 0
    assert "# Reversibility Registry" in capsys.readouterr().out
