# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""CLI for multi-agent drift scenarios."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .conversation import AlertSeverity
from .monitor import MultiAgentDriftMonitor


def load_scenario(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("scenario must be a JSON object")
    return data


def scan_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    monitor = MultiAgentDriftMonitor()
    drift_report = monitor.scan_drift(scenario.get("sources", []))
    alerts = []
    for message in scenario.get("messages", []):
        alert = monitor.analyze_message(
            str(message.get("conversation_id", "default")),
            str(message.get("sender", "agent-a")),
            str(message.get("receiver", "agent-b")),
            str(message.get("content", "")),
        )
        alerts.append(alert)

    critical_drift = sum(1 for finding in drift_report.findings if finding.severity == "critical")
    critical_alerts = sum(1 for alert in alerts if alert.severity == AlertSeverity.CRITICAL)
    return {
        "safe": critical_drift == 0 and critical_alerts == 0,
        "summary": {
            "drift_findings": len(drift_report.findings),
            "critical_drift": critical_drift,
            "conversation_alerts": len(alerts),
            "critical_alerts": critical_alerts,
        },
        "drift_report": drift_report.to_dict(),
        "conversation_alerts": [alert.to_dict() for alert in alerts],
        "health": monitor.health_report(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="multi-agent-drift",
        description="Scan multi-agent drift, conversation escalation, and handoff state.",
    )
    subparsers = parser.add_subparsers(dest="command")
    scan_parser = subparsers.add_parser("scan", help="Scan a multi-agent drift scenario")
    scan_parser.add_argument("scenario", help="Path to scenario JSON")
    scan_parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    try:
        if args.command == "scan":
            report = scan_scenario(load_scenario(args.scenario))
            if args.format == "json":
                print(json.dumps(report, indent=2))
            else:
                print(_to_markdown(report, args.scenario))
            return 0 if report["safe"] else 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 1


def _to_markdown(report: dict[str, Any], label: str) -> str:
    summary = report["summary"]
    lines = [
        f"# Multi-Agent Drift Report: {label}",
        "",
        f"- Safe: {report['safe']}",
        f"- Drift Findings: {summary['drift_findings']}",
        f"- Critical Drift: {summary['critical_drift']}",
        f"- Conversation Alerts: {summary['conversation_alerts']}",
        f"- Critical Alerts: {summary['critical_alerts']}",
        "",
        "## Drift Findings",
    ]
    for finding in report["drift_report"]["findings"]:
        lines.append(
            f"- **{finding['severity']}** {finding['drift_type']} `{finding['field']}`: {finding['message']}"
        )
    lines.append("")
    lines.append("## Conversation Alerts")
    for alert in report["conversation_alerts"]:
        lines.append(
            f"- **{alert['severity']}** {alert['sender']} -> {alert['receiver']}: {alert['action']}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())

