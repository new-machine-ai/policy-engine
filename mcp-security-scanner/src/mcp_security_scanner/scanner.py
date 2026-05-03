# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""MCP tool-definition scanning for supply-chain attacks.

This module ports the Agent Governance Toolkit MCP scanner concepts into a
small package that can run next to ``policy-engine``. It scans what an agent
loads before any tool call executes: MCP tool descriptions, input schemas,
server boundaries, and previously registered fingerprints.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from .audit import AuditSink, InMemoryAuditSink


class MCPThreatType(str, Enum):
    """Classification of an MCP-layer threat."""

    TOOL_POISONING = "tool_poisoning"
    RUG_PULL = "rug_pull"
    CROSS_SERVER_ATTACK = "cross_server_attack"
    CONFUSED_DEPUTY = "confused_deputy"
    HIDDEN_INSTRUCTION = "hidden_instruction"
    DESCRIPTION_INJECTION = "description_injection"


class MCPSeverity(str, Enum):
    """Severity of an MCP threat."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class MCPThreat:
    """A single threat found in an MCP tool definition."""

    threat_type: MCPThreatType
    severity: MCPSeverity
    tool_name: str
    server_name: str
    message: str
    matched_pattern: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "threat_type": self.threat_type.value,
            "severity": self.severity.value,
            "tool_name": self.tool_name,
            "server_name": self.server_name,
            "message": self.message,
            "matched_pattern": self.matched_pattern,
            "details": dict(self.details),
        }


@dataclass
class ToolFingerprint:
    """Cryptographic fingerprint of a tool definition."""

    tool_name: str
    server_name: str
    description_hash: str
    schema_hash: str
    tool_hash: str
    first_seen: float
    last_seen: float
    version: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "server_name": self.server_name,
            "description_hash": self.description_hash,
            "schema_hash": self.schema_hash,
            "tool_hash": self.tool_hash,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "version": self.version,
        }


@dataclass(frozen=True)
class ScanResult:
    """Aggregate outcome of scanning one or more tools."""

    safe: bool
    threats: list[MCPThreat]
    tools_scanned: int
    tools_flagged: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "safe": self.safe,
            "tools_scanned": self.tools_scanned,
            "tools_flagged": self.tools_flagged,
            "threats": [threat.to_dict() for threat in self.threats],
        }


_INVISIBLE_UNICODE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[\u200b\u200c\u200d\ufeff]"),
    re.compile(r"[\u202a-\u202e]"),
    re.compile(r"[\u2066-\u2069]"),
    re.compile(r"[\u00ad]"),
    re.compile(r"[\u2060\u180e]"),
)
_HIDDEN_COMMENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<!--.*?-->", re.DOTALL),
    re.compile(r"\[//\]:\s*#\s*\(.*?\)", re.DOTALL),
    re.compile(r"\[comment\]:\s*<>\s*\(.*?\)", re.DOTALL),
)
_HIDDEN_INSTRUCTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"override\s+(the\s+)?(previous|above|original)", re.IGNORECASE),
    re.compile(r"instead\s+of\s+(the\s+)?(above|previous|described)", re.IGNORECASE),
    re.compile(r"actually\s+do", re.IGNORECASE),
    re.compile(r"\bsystem\s*:", re.IGNORECASE),
    re.compile(r"\bassistant\s*:", re.IGNORECASE),
    re.compile(r"do\s+not\s+follow", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(above|prior|previous)", re.IGNORECASE),
)
_ENCODED_PAYLOAD_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),
    re.compile(r"(?:\\x[0-9a-fA-F]{2}){4,}"),
)
_EXFILTRATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcurl\b", re.IGNORECASE),
    re.compile(r"\bwget\b", re.IGNORECASE),
    re.compile(r"\bfetch\s*\(", re.IGNORECASE),
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"\bsend\s+email\b", re.IGNORECASE),
    re.compile(r"\bsend\s+to\b", re.IGNORECASE),
    re.compile(r"\bpost\s+to\b", re.IGNORECASE),
    re.compile(r"include\s+the\s+contents?\s+of\b", re.IGNORECASE),
)
_PRIVILEGE_ESCALATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsudo\b", re.IGNORECASE),
    re.compile(r"\badmin\s+access\b", re.IGNORECASE),
    re.compile(r"\broot\s+access\b", re.IGNORECASE),
    re.compile(r"\belevate\s+privile", re.IGNORECASE),
    re.compile(r"\bexec\s*\(", re.IGNORECASE),
    re.compile(r"\beval\s*\(", re.IGNORECASE),
)
_ROLE_OVERRIDE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"you\s+are\b", re.IGNORECASE),
    re.compile(r"your\s+task\s+is\b", re.IGNORECASE),
    re.compile(r"respond\s+with\b", re.IGNORECASE),
    re.compile(r"always\s+return\b", re.IGNORECASE),
    re.compile(r"you\s+must\b", re.IGNORECASE),
    re.compile(r"your\s+role\s+is\b", re.IGNORECASE),
)
_EXCESSIVE_WHITESPACE_PATTERN = re.compile(r"\n{5,}.+", re.DOTALL)
_SUSPICIOUS_DECODED_KEYWORDS = (
    "ignore",
    "override",
    "system",
    "password",
    "secret",
    "admin",
    "root",
    "exec",
    "eval",
    "import os",
    "send",
    "curl",
    "fetch",
)
_SUSPICIOUS_SCHEMA_FIELDS = (
    "system_prompt",
    "instructions",
    "override",
    "command",
    "exec",
    "eval",
    "callback_url",
    "webhook",
    "target_url",
)


class MCPSecurityScanner:
    """Scan MCP tool definitions before those tools are exposed to an agent."""

    def __init__(
        self,
        *,
        audit_sink: AuditSink | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._tool_registry: dict[str, ToolFingerprint] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._audit_sink = audit_sink or InMemoryAuditSink()
        self._clock = clock

    def scan_tool(
        self,
        tool_name: str,
        description: str,
        schema: dict[str, Any] | None = None,
        server_name: str = "unknown",
    ) -> list[MCPThreat]:
        """Scan a single MCP tool definition for poisoning and supply-chain risk."""
        description = description or ""
        try:
            threats: list[MCPThreat] = []
            threats.extend(self._check_hidden_instructions(description, tool_name, server_name))
            threats.extend(self._check_description_injection(description, tool_name, server_name))
            if schema is not None:
                threats.extend(self._check_schema_abuse(schema, tool_name, server_name))
            threats.extend(self._check_cross_server(tool_name, server_name))

            rug_pull = self.check_rug_pull(tool_name, description, schema, server_name)
            if rug_pull is not None:
                threats.append(rug_pull)

            self._record_scan_audit(tool_name, server_name, description, schema, threats)
            return threats
        except Exception:
            threat = MCPThreat(
                threat_type=MCPThreatType.TOOL_POISONING,
                severity=MCPSeverity.CRITICAL,
                tool_name=tool_name,
                server_name=server_name,
                message="Scan error - fail closed",
            )
            self._record_scan_audit(tool_name, server_name, description, schema, [threat])
            return [threat]

    def scan_server(self, server_name: str, tools: list[dict[str, Any]]) -> ScanResult:
        """Scan all tool definitions advertised by one MCP server."""
        all_threats: list[MCPThreat] = []
        flagged: set[str] = set()
        for tool in tools:
            name = str(tool.get("name", "unknown"))
            description = str(tool.get("description", ""))
            schema = tool.get("inputSchema") or tool.get("input_schema")
            threats = self.scan_tool(name, description, schema, server_name)
            if threats:
                flagged.add(name)
                all_threats.extend(threats)
            self.register_tool(name, description, schema, server_name)
        return ScanResult(
            safe=not any(t.severity == MCPSeverity.CRITICAL for t in all_threats),
            threats=all_threats,
            tools_scanned=len(tools),
            tools_flagged=len(flagged),
        )

    def register_tool(
        self,
        tool_name: str,
        description: str,
        schema: dict[str, Any] | None,
        server_name: str,
    ) -> ToolFingerprint:
        """Register a tool definition fingerprint for later rug-pull checks."""
        key = self._registry_key(server_name, tool_name)
        now = self._clock()
        description_hash = _sha256_text(description or "")
        schema_hash = _sha256_json(schema or {})
        tool_hash = _tool_definition_hash(tool_name, description or "", schema)

        existing = self._tool_registry.get(key)
        if existing is not None:
            if (
                existing.description_hash != description_hash
                or existing.schema_hash != schema_hash
                or existing.tool_hash != tool_hash
            ):
                existing.description_hash = description_hash
                existing.schema_hash = schema_hash
                existing.tool_hash = tool_hash
                existing.version += 1
            existing.last_seen = now
            return existing

        fingerprint = ToolFingerprint(
            tool_name=tool_name,
            server_name=server_name,
            description_hash=description_hash,
            schema_hash=schema_hash,
            tool_hash=tool_hash,
            first_seen=now,
            last_seen=now,
            version=1,
        )
        self._tool_registry[key] = fingerprint
        return fingerprint

    def check_rug_pull(
        self,
        tool_name: str,
        description: str,
        schema: dict[str, Any] | None,
        server_name: str,
    ) -> MCPThreat | None:
        """Return a threat if a registered tool definition changed silently."""
        existing = self._tool_registry.get(self._registry_key(server_name, tool_name))
        if existing is None:
            return None

        description_hash = _sha256_text(description or "")
        schema_hash = _sha256_json(schema or {})
        changed: list[str] = []
        if existing.description_hash != description_hash:
            changed.append("description")
        if existing.schema_hash != schema_hash:
            changed.append("schema")

        if not changed:
            return None
        return MCPThreat(
            threat_type=MCPThreatType.RUG_PULL,
            severity=MCPSeverity.CRITICAL,
            tool_name=tool_name,
            server_name=server_name,
            message=f"Tool definition changed since registration: {', '.join(changed)}",
            details={"changed_fields": changed, "previous_version": existing.version},
        )

    @property
    def audit_log(self) -> list[dict[str, Any]]:
        """Return scan audit records without raw descriptions or schemas."""
        return [dict(entry) for entry in self._audit_log]

    @property
    def fingerprints(self) -> dict[str, ToolFingerprint]:
        """Return a shallow copy of registered tool fingerprints."""
        return dict(self._tool_registry)

    def _check_hidden_instructions(
        self, description: str, tool_name: str, server_name: str
    ) -> list[MCPThreat]:
        threats: list[MCPThreat] = []

        for pattern in _INVISIBLE_UNICODE_PATTERNS:
            match = pattern.search(description)
            if match:
                threats.append(
                    MCPThreat(
                        threat_type=MCPThreatType.HIDDEN_INSTRUCTION,
                        severity=MCPSeverity.CRITICAL,
                        tool_name=tool_name,
                        server_name=server_name,
                        message="Invisible unicode characters detected in tool description",
                        matched_pattern=pattern.pattern,
                        details={"char_ord": ord(match.group(0)[0])},
                    )
                )
                break

        for pattern in _HIDDEN_COMMENT_PATTERNS:
            if pattern.search(description):
                threats.append(
                    MCPThreat(
                        threat_type=MCPThreatType.HIDDEN_INSTRUCTION,
                        severity=MCPSeverity.CRITICAL,
                        tool_name=tool_name,
                        server_name=server_name,
                        message="Hidden comment detected in tool description",
                        matched_pattern=pattern.pattern,
                    )
                )

        for pattern in _ENCODED_PAYLOAD_PATTERNS:
            match = pattern.search(description)
            if not match:
                continue
            candidate = match.group(0)
            if candidate.startswith("\\x") or _encoded_payload_is_suspicious(candidate):
                threats.append(
                    MCPThreat(
                        threat_type=MCPThreatType.HIDDEN_INSTRUCTION,
                        severity=MCPSeverity.WARNING,
                        tool_name=tool_name,
                        server_name=server_name,
                        message="Encoded payload detected in tool description",
                        matched_pattern=pattern.pattern,
                    )
                )

        if _EXCESSIVE_WHITESPACE_PATTERN.search(description):
            threats.append(
                MCPThreat(
                    threat_type=MCPThreatType.HIDDEN_INSTRUCTION,
                    severity=MCPSeverity.WARNING,
                    tool_name=tool_name,
                    server_name=server_name,
                    message="Instructions hidden after excessive whitespace",
                    matched_pattern=_EXCESSIVE_WHITESPACE_PATTERN.pattern,
                )
            )

        for pattern in _HIDDEN_INSTRUCTION_PATTERNS:
            if pattern.search(description):
                threats.append(
                    MCPThreat(
                        threat_type=MCPThreatType.HIDDEN_INSTRUCTION,
                        severity=MCPSeverity.CRITICAL,
                        tool_name=tool_name,
                        server_name=server_name,
                        message="Instruction-like pattern in tool description",
                        matched_pattern=pattern.pattern,
                    )
                )
        return threats

    def _check_description_injection(
        self, description: str, tool_name: str, server_name: str
    ) -> list[MCPThreat]:
        threats: list[MCPThreat] = []
        for pattern in _ROLE_OVERRIDE_PATTERNS:
            if pattern.search(description):
                threats.append(
                    MCPThreat(
                        threat_type=MCPThreatType.DESCRIPTION_INJECTION,
                        severity=MCPSeverity.WARNING,
                        tool_name=tool_name,
                        server_name=server_name,
                        message="Role override pattern in tool description",
                        matched_pattern=pattern.pattern,
                    )
                )
        for pattern in _EXFILTRATION_PATTERNS + _PRIVILEGE_ESCALATION_PATTERNS:
            if pattern.search(description):
                threats.append(
                    MCPThreat(
                        threat_type=MCPThreatType.DESCRIPTION_INJECTION,
                        severity=MCPSeverity.CRITICAL,
                        tool_name=tool_name,
                        server_name=server_name,
                        message="Dangerous instruction pattern in tool description",
                        matched_pattern=pattern.pattern,
                    )
                )
        return threats

    def _check_schema_abuse(
        self, schema: dict[str, Any], tool_name: str, server_name: str
    ) -> list[MCPThreat]:
        threats: list[MCPThreat] = []
        if schema.get("type") == "object" and not schema.get("properties"):
            if schema.get("additionalProperties") is not False:
                threats.append(
                    MCPThreat(
                        threat_type=MCPThreatType.TOOL_POISONING,
                        severity=MCPSeverity.WARNING,
                        tool_name=tool_name,
                        server_name=server_name,
                        message="Overly permissive schema: object with no defined properties",
                    )
                )

        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        if not isinstance(properties, dict):
            return threats

        for prop_name, prop_def in properties.items():
            if not isinstance(prop_def, dict):
                continue
            prop_lower = str(prop_name).lower()
            if prop_name in required and any(name in prop_lower for name in _SUSPICIOUS_SCHEMA_FIELDS):
                threats.append(
                    MCPThreat(
                        threat_type=MCPThreatType.TOOL_POISONING,
                        severity=MCPSeverity.CRITICAL,
                        tool_name=tool_name,
                        server_name=server_name,
                        message=f"Suspicious required schema field: {prop_name}",
                        details={"field_name": prop_name},
                    )
                )

            default_value = prop_def.get("default")
            if isinstance(default_value, str) and _matches_any(default_value, _HIDDEN_INSTRUCTION_PATTERNS):
                threats.append(
                    MCPThreat(
                        threat_type=MCPThreatType.TOOL_POISONING,
                        severity=MCPSeverity.CRITICAL,
                        tool_name=tool_name,
                        server_name=server_name,
                        message=f"Instruction in default value for field: {prop_name}",
                        details={"field_name": prop_name},
                    )
                )

            description = prop_def.get("description")
            if isinstance(description, str) and _matches_any(description, _HIDDEN_INSTRUCTION_PATTERNS):
                threats.append(
                    MCPThreat(
                        threat_type=MCPThreatType.TOOL_POISONING,
                        severity=MCPSeverity.CRITICAL,
                        tool_name=tool_name,
                        server_name=server_name,
                        message=f"Hidden instruction in schema field description: {prop_name}",
                        details={"field_name": prop_name},
                    )
                )
        return threats

    def _check_cross_server(self, tool_name: str, server_name: str) -> list[MCPThreat]:
        threats: list[MCPThreat] = []
        for fingerprint in self._tool_registry.values():
            if fingerprint.server_name == server_name:
                continue
            if fingerprint.tool_name == tool_name:
                threats.append(
                    MCPThreat(
                        threat_type=MCPThreatType.CROSS_SERVER_ATTACK,
                        severity=MCPSeverity.CRITICAL,
                        tool_name=tool_name,
                        server_name=server_name,
                        message=(
                            f"Tool '{tool_name}' already registered from server "
                            f"'{fingerprint.server_name}'"
                        ),
                        details={"original_server": fingerprint.server_name},
                    )
                )
            elif _is_typosquat(tool_name, fingerprint.tool_name):
                threats.append(
                    MCPThreat(
                        threat_type=MCPThreatType.CROSS_SERVER_ATTACK,
                        severity=MCPSeverity.WARNING,
                        tool_name=tool_name,
                        server_name=server_name,
                        message=(
                            f"Tool name '{tool_name}' resembles '{fingerprint.tool_name}' "
                            f"from server '{fingerprint.server_name}'"
                        ),
                        details={
                            "similar_tool": fingerprint.tool_name,
                            "similar_server": fingerprint.server_name,
                        },
                    )
                )
        return threats

    def _record_scan_audit(
        self,
        tool_name: str,
        server_name: str,
        description: str,
        schema: dict[str, Any] | None,
        threats: list[MCPThreat],
    ) -> None:
        record = {
            "timestamp": datetime.fromtimestamp(self._clock(), timezone.utc).isoformat(),
            "action": "scan_tool",
            "tool_name": tool_name,
            "server_name": server_name,
            "description_hash": _sha256_text(description or ""),
            "schema_hash": _sha256_json(schema or {}),
            "tool_definition_hash": _tool_definition_hash(tool_name, description or "", schema),
            "threats_found": len(threats),
            "threat_types": [threat.threat_type.value for threat in threats],
            "severities": [threat.severity.value for threat in threats],
        }
        self._audit_log.append(record)
        self._audit_sink.record(record)

    @staticmethod
    def _registry_key(server_name: str, tool_name: str) -> str:
        return f"{server_name}::{tool_name}"


def _matches_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _encoded_payload_is_suspicious(candidate: str) -> bool:
    if len(candidate) < 40:
        return False
    try:
        decoded = base64.b64decode(candidate).decode("utf-8", errors="ignore")
    except Exception:
        return True
    decoded_lower = decoded.lower()
    return any(keyword in decoded_lower for keyword in _SUSPICIOUS_DECODED_KEYWORDS)


def _is_typosquat(name_a: str, name_b: str) -> bool:
    if name_a == name_b:
        return False
    left = name_a.lower()
    right = name_b.lower()
    if abs(len(left) - len(right)) > 2 or min(len(left), len(right)) < 4:
        return False
    distance = _levenshtein(left, right)
    return 1 <= distance <= 2


def _levenshtein(left: str, right: str) -> int:
    if len(left) < len(right):
        return _levenshtein(right, left)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left):
        current = [i + 1]
        for j, right_char in enumerate(right):
            cost = 0 if left_char == right_char else 1
            current.append(min(current[j] + 1, previous[j + 1] + 1, previous[j] + cost))
        previous = current
    return previous[-1]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _tool_definition_hash(
    tool_name: str, description: str, schema: dict[str, Any] | None
) -> str:
    payload = {"name": tool_name, "description": description, "inputSchema": schema or {}}
    return _sha256_json(payload)
