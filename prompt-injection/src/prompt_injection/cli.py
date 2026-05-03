# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""CLI for prompt-injection and untrusted-content checks."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any

from .cve import McpCveFeed
from .detector import DetectionConfig, PromptInjectionDetector
from .mcp import MCPResponseScanner
from .signing import MCPMessageSigner, MCPSignedEnvelope


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prompt-injection",
        description="Scan prompts and untrusted content for prompt injection risks.",
    )
    subparsers = parser.add_subparsers(dest="command")

    prompt_parser = subparsers.add_parser("scan-prompt", help="Scan a prompt or file")
    prompt_parser.add_argument("text", nargs="?", help="Prompt text to scan")
    prompt_parser.add_argument("--file", help="File containing prompt text")
    prompt_parser.add_argument("--source", default="cli", help="Audit source label")
    prompt_parser.add_argument("--sensitivity", choices=["strict", "balanced", "permissive"], default="balanced")
    prompt_parser.add_argument("--format", choices=["json", "markdown"], default="markdown")

    response_parser = subparsers.add_parser("scan-response", help="Scan untrusted tool response content")
    response_parser.add_argument("text", nargs="?", help="Response text to scan")
    response_parser.add_argument("--file", help="File containing response text")
    response_parser.add_argument("--tool-name", default="unknown")
    response_parser.add_argument("--format", choices=["json", "markdown"], default="markdown")

    sign_parser = subparsers.add_parser("sign", help="Sign a payload")
    sign_parser.add_argument("payload", nargs="?", help="Payload text to sign")
    sign_parser.add_argument("--file", help="File containing payload")
    sign_parser.add_argument("--key-base64", required=True)
    sign_parser.add_argument("--sender-id")

    verify_parser = subparsers.add_parser("verify", help="Verify a signed envelope JSON file")
    verify_parser.add_argument("--envelope", required=True)
    verify_parser.add_argument("--key-base64", required=True)

    key_parser = subparsers.add_parser("generate-key", help="Generate a base64 signing key")
    key_parser.set_defaults(command="generate-key")

    cve_parser = subparsers.add_parser("cve-check", help="Check a package/version against OSV")
    cve_parser.add_argument("--package", required=True)
    cve_parser.add_argument("--version", required=True)
    cve_parser.add_argument("--ecosystem", default="npm", choices=["npm", "PyPI", "crates.io", "Go"])
    cve_parser.add_argument("--format", choices=["json", "markdown"], default="markdown")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    try:
        if args.command == "scan-prompt":
            text = _read_text_arg(args.text, args.file, "prompt")
            detector = PromptInjectionDetector(DetectionConfig(sensitivity=args.sensitivity))
            result = detector.detect(text, source=args.source)
            output = result.to_dict()
            _print(output, args.format, _prompt_markdown(output))
            return 1 if result.is_injection else 0

        if args.command == "scan-response":
            text = _read_text_arg(args.text, args.file, "response")
            result = MCPResponseScanner().scan_response(text, tool_name=args.tool_name)
            output = result.to_dict()
            _print(output, args.format, _response_markdown(output))
            return 1 if not result.is_safe else 0

        if args.command == "sign":
            payload = _read_text_arg(args.payload, args.file, "payload")
            signer = MCPMessageSigner.from_base64_key(args.key_base64)
            envelope = signer.sign_message(payload, sender_id=args.sender_id)
            print(json.dumps(envelope.to_dict(), indent=2))
            return 0

        if args.command == "verify":
            data = json.loads(Path(args.envelope).read_text(encoding="utf-8"))
            signer = MCPMessageSigner.from_base64_key(args.key_base64)
            result = signer.verify_message(MCPSignedEnvelope.from_dict(data))
            print(json.dumps(result.to_dict(), indent=2))
            return 0 if result.is_valid else 1

        if args.command == "generate-key":
            print(base64.b64encode(MCPMessageSigner.generate_key()).decode("ascii"))
            return 0

        if args.command == "cve-check":
            feed = McpCveFeed()
            records = feed.check_package(args.package, args.version, args.ecosystem)
            output = {
                "package": args.package,
                "version": args.version,
                "ecosystem": args.ecosystem,
                "vulnerabilities": [record.to_dict() for record in records],
                "summary": _severity_summary(records),
            }
            _print(output, args.format, _cve_markdown(output))
            return 1 if any(record.severity in {"CRITICAL", "HIGH"} for record in records) else 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 1


def _read_text_arg(text: str | None, path: str | None, label: str) -> str:
    if text and path:
        raise ValueError(f"provide either {label} text or --file, not both")
    if path:
        return Path(path).read_text(encoding="utf-8")
    if text is None:
        raise ValueError(f"missing {label} text or --file")
    return text


def _print(output: dict[str, Any], output_format: str, markdown: str) -> None:
    if output_format == "json":
        print(json.dumps(output, indent=2))
    else:
        print(markdown)


def _prompt_markdown(output: dict[str, Any]) -> str:
    lines = [
        "# Prompt Injection Scan",
        "",
        f"- Injection: {output['is_injection']}",
        f"- Threat Level: {output['threat_level']}",
        f"- Type: {output['injection_type']}",
        f"- Confidence: {output['confidence']}",
        f"- Explanation: {output['explanation']}",
    ]
    if output["matched_patterns"]:
        lines.append("- Matched Patterns:")
        lines.extend(f"  - `{pattern}`" for pattern in output["matched_patterns"])
    return "\n".join(lines)


def _response_markdown(output: dict[str, Any]) -> str:
    lines = [
        "# MCP Response Scan",
        "",
        f"- Safe: {output['is_safe']}",
        f"- Tool: {output['tool_name']}",
        f"- Threats: {len(output['threats'])}",
    ]
    for threat in output["threats"]:
        lines.append(f"- **{threat['category']}**: {threat['description']}")
    return "\n".join(lines)


def _cve_markdown(output: dict[str, Any]) -> str:
    lines = [
        "# CVE Check",
        "",
        f"- Package: {output['package']}",
        f"- Version: {output['version']}",
        f"- Ecosystem: {output['ecosystem']}",
        f"- Vulnerabilities: {len(output['vulnerabilities'])}",
    ]
    for record in output["vulnerabilities"]:
        lines.append(f"- **{record['severity']}** {record['cve_id']}: {record['summary']}")
    return "\n".join(lines)


def _severity_summary(records: list[Any]) -> dict[str, int]:
    summary = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    for record in records:
        summary[record.severity] = summary.get(record.severity, 0) + 1
    return summary


if __name__ == "__main__":
    raise SystemExit(main())
