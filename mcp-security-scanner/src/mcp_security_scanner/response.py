# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Scan MCP tool responses before they are returned to an LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


_INSTRUCTION_TAG_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"<(?:important|system|instruction|instructions|hidden|inject|admin|override|prompt|context|role)\b[^>]*>",
        re.IGNORECASE,
    ),
    re.compile(r"</(?:important|system|instruction|instructions|hidden|inject|admin|override|prompt|context|role)>", re.IGNORECASE),
    re.compile(r"\[(?:system|admin|instructions?)\]", re.IGNORECASE),
)
_IMPERATIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(?:all\s+)?previous\s+(?:instructions?|context|rules?)", re.IGNORECASE),
    re.compile(r"(?:forget|disregard|override)\s+(?:all\s+)?(?:previous|above|prior|earlier)", re.IGNORECASE),
    re.compile(r"\bexecute\s+this\b", re.IGNORECASE),
    re.compile(r"\byou\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"\bnew\s+(?:role|instruction|directive|persona)\s*:", re.IGNORECASE),
    re.compile(r"\bfrom\s+now\s+on\b", re.IGNORECASE),
    re.compile(r"\bdo\s+not\s+(?:follow|obey|listen)\b", re.IGNORECASE),
)
_URL_PATTERN = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
_EXFILTRATION_URL_PATTERN = re.compile(
    r"(?i)(?:\b(?:api[_-]?key|token|secret|payload|data|dump|upload|exfil|webhook)\b|webhook\.site|requestbin|pastebin|ngrok|transfer\.sh)"
)
_CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("OpenAI API key", re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{18,}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp|ghs)_[A-Za-z0-9]{20,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    ("Bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._\-+/=]{16,}\b")),
    (
        "Generic API secret",
        re.compile(r"(?i)\b(?:api[_-]?key|client[_-]?secret|secret|token)\b\s*[:=]\s*['\"]?[^\s'\";]{6,}"),
    ),
)


@dataclass(frozen=True)
class MCPResponseThreat:
    """A threat detected in tool output."""

    category: str
    description: str
    matched_pattern: str | None = None
    details: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "description": self.description,
            "matched_pattern": self.matched_pattern,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class MCPResponseScanResult:
    """Result of scanning an MCP tool response."""

    is_safe: bool
    tool_name: str
    threats: list[MCPResponseThreat] = field(default_factory=list)

    @classmethod
    def safe(cls, tool_name: str) -> "MCPResponseScanResult":
        return cls(is_safe=True, tool_name=tool_name, threats=[])

    @classmethod
    def unsafe(
        cls,
        tool_name: str,
        *,
        reason: str,
        category: str = "error",
    ) -> "MCPResponseScanResult":
        return cls(
            is_safe=False,
            tool_name=tool_name,
            threats=[MCPResponseThreat(category=category, description=reason)],
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "is_safe": self.is_safe,
            "tool_name": self.tool_name,
            "threats": [threat.to_dict() for threat in self.threats],
        }


class MCPResponseScanner:
    """Scan tool responses for prompt injection, credential leaks, and exfil URLs."""

    def scan_response(
        self,
        response_content: str | None,
        tool_name: str = "unknown",
    ) -> MCPResponseScanResult:
        try:
            if not response_content:
                return MCPResponseScanResult.safe(tool_name)

            threats: list[MCPResponseThreat] = []
            threats.extend(
                self._scan_patterns(
                    response_content,
                    patterns=_INSTRUCTION_TAG_PATTERNS,
                    category="instruction_injection",
                    description="Instruction tag detected in tool response.",
                    expose_match=False,
                )
            )
            threats.extend(
                self._scan_patterns(
                    response_content,
                    patterns=_IMPERATIVE_PATTERNS,
                    category="prompt_injection",
                    description="Imperative instruction detected in tool response.",
                    expose_match=False,
                )
            )
            threats.extend(self._scan_credential_leaks(response_content))
            threats.extend(self._scan_exfiltration_urls(response_content))

            if not threats:
                return MCPResponseScanResult.safe(tool_name)
            return MCPResponseScanResult(is_safe=False, tool_name=tool_name, threats=threats)
        except Exception:
            return MCPResponseScanResult.unsafe(
                tool_name,
                reason="Response scanner error (fail-closed).",
            )

    def sanitize_response(
        self,
        response_content: str | None,
        tool_name: str = "unknown",
    ) -> tuple[str, list[MCPResponseThreat]]:
        try:
            if not response_content:
                return "", []

            sanitized = response_content
            stripped: list[MCPResponseThreat] = []
            for pattern in _INSTRUCTION_TAG_PATTERNS:
                if pattern.search(sanitized):
                    stripped.append(
                        MCPResponseThreat(
                            category="instruction_injection",
                            description="Instruction tag stripped from tool response.",
                            matched_pattern=pattern.pattern,
                        )
                    )
                sanitized = pattern.sub("", sanitized)
            return sanitized, stripped
        except Exception:
            return "", [
                MCPResponseThreat(
                    category="error",
                    description=f"Response sanitization failed for tool '{tool_name}' (fail-closed).",
                )
            ]

    @staticmethod
    def _scan_patterns(
        content: str,
        *,
        patterns: tuple[re.Pattern[str], ...],
        category: str,
        description: str,
        expose_match: bool,
    ) -> list[MCPResponseThreat]:
        threats: list[MCPResponseThreat] = []
        for pattern in patterns:
            for match in pattern.finditer(content):
                threats.append(
                    MCPResponseThreat(
                        category=category,
                        description=description,
                        matched_pattern=match.group(0) if expose_match else pattern.pattern,
                    )
                )
        return threats

    @staticmethod
    def _scan_credential_leaks(content: str) -> list[MCPResponseThreat]:
        threats: list[MCPResponseThreat] = []
        for name, pattern in _CREDENTIAL_PATTERNS:
            if pattern.search(content):
                threats.append(
                    MCPResponseThreat(
                        category="credential_leak",
                        description=f"{name} detected in tool response.",
                        matched_pattern=name,
                        details={"credential_type": name},
                    )
                )
        return threats

    @staticmethod
    def _scan_exfiltration_urls(content: str) -> list[MCPResponseThreat]:
        threats: list[MCPResponseThreat] = []
        for match in _URL_PATTERN.finditer(content):
            url = match.group(0)
            if _EXFILTRATION_URL_PATTERN.search(url):
                threats.append(
                    MCPResponseThreat(
                        category="data_exfiltration",
                        description="Potential data exfiltration URL detected in tool response.",
                        matched_pattern="exfiltration_url",
                    )
                )
        return threats

