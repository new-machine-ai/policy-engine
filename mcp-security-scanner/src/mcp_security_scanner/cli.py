# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Command-line interface for MCP security scanning."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .scanner import MCPSecurityScanner, MCPSeverity


def load_config(path: str | Path) -> Any:
    config_path = Path(path)
    text = config_path.read_text(encoding="utf-8")
    if config_path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("PyYAML is required for YAML configs: pip install mcp-security-scanner[yaml]") from exc
        return yaml.safe_load(text)
    return json.loads(text)


def parse_config(config: Any, *, server_filter: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Normalize supported MCP config shapes to ``server -> tools``."""
    if isinstance(config, list):
        return {"tools": [tool for tool in config if isinstance(tool, dict)]}
    if not isinstance(config, dict):
        raise ValueError("MCP config must be an object or a list of tools")

    servers = config.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("mcpServers must be an object")

    parsed: dict[str, list[dict[str, Any]]] = {}
    for server_name, server_config in servers.items():
        if server_filter and server_name != server_filter:
            continue
        tools = []
        if isinstance(server_config, dict):
            maybe_tools = server_config.get("tools", [])
            if isinstance(maybe_tools, list):
                tools = [tool for tool in maybe_tools if isinstance(tool, dict)]
        parsed[str(server_name)] = tools
    return parsed


def run_scan(config: Any, *, server_filter: str | None = None) -> dict[str, Any]:
    scanner = MCPSecurityScanner()
    servers = parse_config(config, server_filter=server_filter)
    results = []
    all_threats = []
    for server_name, tools in servers.items():
        result = scanner.scan_server(server_name, tools)
        results.append({"server": server_name, **result.to_dict()})
        all_threats.extend(result.threats)
    critical = sum(1 for threat in all_threats if threat.severity == MCPSeverity.CRITICAL)
    warning = sum(1 for threat in all_threats if threat.severity == MCPSeverity.WARNING)
    return {
        "safe": critical == 0,
        "summary": {
            "servers": len(servers),
            "tools_scanned": sum(item["tools_scanned"] for item in results),
            "threats": len(all_threats),
            "critical": critical,
            "warning": warning,
        },
        "results": results,
        "audit": scanner.audit_log,
    }


def compute_fingerprints(config: Any, *, server_filter: str | None = None) -> dict[str, str]:
    scanner = MCPSecurityScanner()
    fingerprints: dict[str, str] = {}
    servers = parse_config(config, server_filter=server_filter)
    for server_name, tools in servers.items():
        if not tools:
            fingerprints[server_name] = _server_hash(server_name)
            continue
        for tool in tools:
            name = str(tool.get("name", "unknown"))
            fp = scanner.register_tool(
                name,
                str(tool.get("description", "")),
                tool.get("inputSchema") or tool.get("input_schema"),
                server_name,
            )
            fingerprints[f"{server_name}::{name}"] = fp.tool_hash
    return fingerprints


def compare_fingerprints(current: dict[str, str], saved: dict[str, str]) -> dict[str, str]:
    diffs: dict[str, str] = {}
    for key, value in current.items():
        if key not in saved:
            diffs[key] = "new"
        elif saved[key] != value:
            diffs[key] = "changed"
    for key in saved:
        if key not in current:
            diffs[key] = "removed"
    return diffs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-security-scan",
        description="Scan MCP tool definitions and configs for supply-chain risk.",
    )
    subparsers = parser.add_subparsers(dest="command")

    scan_parser = subparsers.add_parser("scan", help="Scan an MCP config")
    scan_parser.add_argument("config", help="Path to MCP config JSON/YAML")
    scan_parser.add_argument("--server", default=None, help="Scan only this server")
    scan_parser.add_argument("--format", choices=["json", "table", "markdown"], default="table")
    scan_parser.add_argument("--json", action="store_true", help="Compatibility alias for --format json")

    fp_parser = subparsers.add_parser("fingerprint", help="Compute or compare fingerprints")
    fp_parser.add_argument("config", help="Path to MCP config JSON/YAML")
    fp_parser.add_argument("--server", default=None, help="Fingerprint only this server")
    fp_parser.add_argument("--output", default=None, help="Write fingerprints to this JSON file")
    fp_parser.add_argument("--compare", default=None, help="Compare against saved fingerprint JSON")
    fp_parser.add_argument("--format", choices=["json", "table"], default="table")
    fp_parser.add_argument("--json", action="store_true", help="Compatibility alias for --format json")

    report_parser = subparsers.add_parser("report", help="Generate a full security report")
    report_parser.add_argument("config", help="Path to MCP config JSON/YAML")
    report_parser.add_argument("--server", default=None, help="Report only this server")
    report_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    report_parser.add_argument("--json", action="store_true", help="Compatibility alias for --format json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    try:
        config = load_config(args.config)
        output_format = "json" if getattr(args, "json", False) else args.format

        if args.command == "scan":
            report = run_scan(config, server_filter=args.server)
            _print_scan(report, output_format)
            return 0 if report["safe"] else 1

        if args.command == "fingerprint":
            current = compute_fingerprints(config, server_filter=args.server)
            output: dict[str, Any] = {"fingerprints": current}
            exit_code = 0
            if args.compare:
                saved = json.loads(Path(args.compare).read_text(encoding="utf-8"))
                diffs = compare_fingerprints(current, saved)
                output["diffs"] = diffs
                exit_code = 1 if diffs else 0
            if args.output:
                Path(args.output).write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
                output["output"] = args.output
            _print_fingerprints(output, output_format)
            return exit_code

        if args.command == "report":
            report = run_scan(config, server_filter=args.server)
            _print_report(report, output_format, args.config)
            return 0 if report["safe"] else 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 1


def _print_scan(report: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(report, indent=2))
        return
    if output_format == "markdown":
        _print_report(report, "markdown", "scan")
        return
    print(f"MCP Security Scan: {'PASS' if report['safe'] else 'FAIL'}")
    summary = report["summary"]
    print(
        f"servers={summary['servers']} tools={summary['tools_scanned']} "
        f"threats={summary['threats']} critical={summary['critical']} warning={summary['warning']}"
    )
    for item in report["results"]:
        for threat in item["threats"]:
            print(
                f"- {threat['severity'].upper()} {item['server']}::{threat['tool_name']} "
                f"[{threat['threat_type']}] {threat['message']}"
            )


def _print_fingerprints(output: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(output, indent=2))
        return
    for name, digest in output["fingerprints"].items():
        print(f"{name:40} {digest}")
    if output.get("diffs"):
        print("diffs:")
        for name, status in output["diffs"].items():
            print(f"  {name}: {status}")


def _print_report(report: dict[str, Any], output_format: str, label: str) -> None:
    if output_format == "json":
        print(json.dumps(report, indent=2))
        return
    summary = report["summary"]
    print(f"# MCP Security Report: {label}")
    print()
    print(f"- Safe: {report['safe']}")
    print(f"- Servers: {summary['servers']}")
    print(f"- Tools Scanned: {summary['tools_scanned']}")
    print(f"- Threats: {summary['threats']}")
    print(f"- Critical: {summary['critical']}")
    print(f"- Warning: {summary['warning']}")
    print()
    print("## Findings")
    for item in report["results"]:
        for threat in item["threats"]:
            print(
                f"- **{item['server']}::{threat['tool_name']}** "
                f"({threat['severity'].upper()}, {threat['threat_type']}): {threat['message']}"
            )


def _server_hash(server_name: str) -> str:
    payload = json.dumps({"server": server_name}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
