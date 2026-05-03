# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""CLI for human-loop action gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .escalation import EscalationHandler
from .guard import HumanLoopGuard
from .kill_switch import KillReason, KillSignal, KillSwitch
from .rbac import Role
from .reversibility import ReversibilityChecker, ReversibilityRegistry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="human-loop",
        description="Human approval, role gates, kill switches, and reversibility checks.",
    )
    subparsers = parser.add_subparsers(dest="command")

    check = subparsers.add_parser("check-action", help="Evaluate an action through the human-loop guard")
    check.add_argument("--agent-id", required=True)
    check.add_argument("--session-id", required=True)
    check.add_argument("--action", required=True)
    check.add_argument("--role", choices=[role.value for role in Role])
    check.add_argument("--block-irreversible", action="store_true")
    check.add_argument("--format", choices=["json", "markdown"], default="markdown")

    request = subparsers.add_parser("request-approval", help="Create an approval request")
    request.add_argument("--agent-id", required=True)
    request.add_argument("--action", required=True)
    request.add_argument("--reason", default="human approval requested")
    request.add_argument("--state-file", default=".human-loop-approvals.json")

    approve = subparsers.add_parser("approve", help="Mark a stored request approved")
    approve.add_argument("request_id")
    approve.add_argument("--approver", default="human")
    approve.add_argument("--state-file", default=".human-loop-approvals.json")

    deny = subparsers.add_parser("deny", help="Mark a stored request denied")
    deny.add_argument("request_id")
    deny.add_argument("--approver", default="human")
    deny.add_argument("--state-file", default=".human-loop-approvals.json")

    kill = subparsers.add_parser("kill", help="Apply a kill-switch signal")
    kill.add_argument("--agent-id", required=True)
    kill.add_argument("--session-id", required=True)
    kill.add_argument("--signal", choices=[signal.value for signal in KillSignal], required=True)
    kill.add_argument("--reason", choices=[reason.value for reason in KillReason], default=KillReason.MANUAL.value)
    kill.add_argument("--format", choices=["json", "markdown"], default="markdown")

    classify = subparsers.add_parser("classify", help="Classify action reversibility")
    classify.add_argument("--action", required=True)
    classify.add_argument("--format", choices=["json", "markdown"], default="markdown")

    registry = subparsers.add_parser("registry", help="Registry utilities")
    registry_sub = registry.add_subparsers(dest="registry_command")
    report = registry_sub.add_parser("report", help="Report registry contents")
    report.add_argument("--session-id", default="default")
    report.add_argument("--format", choices=["json", "markdown"], default="markdown")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    try:
        if args.command == "check-action":
            guard = HumanLoopGuard(block_irreversible=args.block_irreversible)
            if args.role:
                guard.rbac.assign_role(args.agent_id, Role(args.role))
            decision = guard.evaluate_action(args.agent_id, args.session_id, args.action)
            output = decision.to_dict()
            _print(output, args.format, _decision_markdown(output))
            return 0 if decision.allowed else 1

        if args.command == "request-approval":
            handler = EscalationHandler(timeout_seconds=0)
            request = handler.escalate(args.agent_id, args.action, args.reason, {})
            state = _load_state(args.state_file)
            state[request.request_id] = request.to_dict()
            _save_state(args.state_file, state)
            print(json.dumps(request.to_dict(), indent=2))
            return 0

        if args.command in {"approve", "deny"}:
            state = _load_state(args.state_file)
            request = state.get(args.request_id)
            if request is None:
                print(json.dumps({"request_id": args.request_id, "accepted": False, "reason": "request not found"}, indent=2))
                return 1
            request["decision"] = "allow" if args.command == "approve" else "deny"
            request["resolved_by"] = args.approver
            state[args.request_id] = request
            _save_state(args.state_file, state)
            print(json.dumps({"request_id": args.request_id, "accepted": True, "decision": request["decision"]}, indent=2))
            return 0

        if args.command == "kill":
            switch = KillSwitch()
            result = switch.kill(
                args.agent_id,
                args.session_id,
                KillReason(args.reason),
                signal=KillSignal(args.signal),
            )
            output = result.to_dict()
            _print(output, args.format, _kill_markdown(output))
            return 1

        if args.command == "classify":
            assessment = ReversibilityChecker().assess(args.action)
            output = assessment.to_dict()
            _print(output, args.format, _classify_markdown(output))
            return 0

        if args.command == "registry" and args.registry_command == "report":
            registry = ReversibilityRegistry(args.session_id)
            output = {
                "session_id": registry.session_id,
                "entries": [entry.to_dict() for entry in registry.entries],
                "non_reversible_actions": registry.non_reversible_actions,
            }
            _print(output, args.format, _registry_markdown(output))
            return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 1


def _load_state(path: str) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def _save_state(path: str, state: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _print(output: dict[str, Any], output_format: str, markdown: str) -> None:
    if output_format == "json":
        print(json.dumps(output, indent=2))
    else:
        print(markdown)


def _decision_markdown(output: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Human Loop Decision",
            "",
            f"- Allowed: {output['allowed']}",
            f"- Decision: {output['decision']}",
            f"- Agent: {output['agent_id']}",
            f"- Action: {output['action']}",
            f"- Role: {output['role']}",
            f"- Reason: {output['reason']}",
        ]
    )


def _kill_markdown(output: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Kill Switch Result",
            "",
            f"- Agent: {output['agent_did']}",
            f"- Signal: {output['signal']}",
            f"- Reason: {output['reason']}",
            f"- Terminated: {output['terminated']}",
            f"- Stopped: {output['stopped']}",
        ]
    )


def _classify_markdown(output: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Reversibility Assessment",
            "",
            f"- Action: {output['action']}",
            f"- Level: {output['level']}",
            f"- Requires Approval: {output['requires_extra_approval']}",
            f"- Reason: {output['reason']}",
        ]
    )


def _registry_markdown(output: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Reversibility Registry",
            "",
            f"- Session: {output['session_id']}",
            f"- Entries: {len(output['entries'])}",
            f"- Non-Reversible Actions: {len(output['non_reversible_actions'])}",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
