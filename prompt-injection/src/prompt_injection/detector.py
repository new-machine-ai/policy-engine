# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Prompt injection detection for untrusted agent input."""

from __future__ import annotations

import base64
import hashlib
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class InjectionType(str, Enum):
    """Classification of a prompt injection attack."""

    DIRECT_OVERRIDE = "direct_override"
    DELIMITER_ATTACK = "delimiter_attack"
    ENCODING_ATTACK = "encoding_attack"
    ROLE_PLAY = "role_play"
    CONTEXT_MANIPULATION = "context_manipulation"
    CANARY_LEAK = "canary_leak"
    MULTI_TURN_ESCALATION = "multi_turn_escalation"


class ThreatLevel(str, Enum):
    """Severity of a detected prompt injection threat."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_THREAT_ORDER = {
    ThreatLevel.NONE: 0,
    ThreatLevel.LOW: 1,
    ThreatLevel.MEDIUM: 2,
    ThreatLevel.HIGH: 3,
    ThreatLevel.CRITICAL: 4,
}
_MIN_LIST_ENTRY_LENGTH = 3


@dataclass(frozen=True)
class DetectionResult:
    """Outcome of scanning one input."""

    is_injection: bool
    threat_level: ThreatLevel
    injection_type: InjectionType | None
    confidence: float
    matched_patterns: list[str] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_injection": self.is_injection,
            "threat_level": self.threat_level.value,
            "injection_type": self.injection_type.value if self.injection_type else None,
            "confidence": round(self.confidence, 4),
            "matched_patterns": list(self.matched_patterns),
            "explanation": self.explanation,
        }


@dataclass
class DetectionConfig:
    """Configuration for prompt injection detection."""

    sensitivity: str = "balanced"
    custom_patterns: list[re.Pattern[str]] = field(default_factory=list)
    blocklist: Sequence[str] = field(default_factory=tuple)
    allowlist: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.sensitivity not in _SENSITIVITY_THRESHOLDS:
            raise ValueError("sensitivity must be one of: strict, balanced, permissive")
        self.allowlist = _validate_terms("allowlist", self.allowlist)
        self.blocklist = _validate_terms("blocklist", self.blocklist)


@dataclass(frozen=True)
class AuditRecord:
    """Immutable record of a detection attempt without raw prompt text."""

    timestamp: datetime
    input_hash: str
    source: str
    result: DetectionResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "input_hash": self.input_hash,
            "source": self.source,
            "result": self.result.to_dict(),
        }


@dataclass
class PromptInjectionConfig:
    """Externalized prompt injection pattern configuration."""

    direct_override_patterns: list[str] = field(default_factory=lambda: [p.pattern for p in _DIRECT_OVERRIDE_PATTERNS])
    delimiter_patterns: list[str] = field(default_factory=lambda: [p.pattern for p in _DELIMITER_PATTERNS])
    role_play_patterns: list[str] = field(default_factory=lambda: [p.pattern for p in _ROLE_PLAY_PATTERNS])
    context_manipulation_patterns: list[str] = field(default_factory=lambda: [p.pattern for p in _CONTEXT_MANIPULATION_PATTERNS])
    multi_turn_patterns: list[str] = field(default_factory=lambda: [p.pattern for p in _MULTI_TURN_PATTERNS])
    encoding_patterns: list[str] = field(default_factory=lambda: [p.pattern for p in _ENCODING_PATTERNS])
    base64_pattern: str = field(default_factory=lambda: _BASE64_PATTERN.pattern)
    suspicious_decoded_keywords: list[str] = field(default_factory=lambda: list(_SUSPICIOUS_DECODED_KEYWORDS))
    sensitivity_thresholds: dict[str, float] = field(default_factory=lambda: dict(_SENSITIVITY_THRESHOLDS))
    sensitivity_min_threat: dict[str, str] = field(default_factory=lambda: {k: v.value for k, v in _SENSITIVITY_MIN_THREAT.items()})


def load_prompt_injection_config(path: str) -> PromptInjectionConfig:
    """Load prompt injection detector config from YAML."""
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("Install prompt-injection[yaml] to load YAML detector configs.") from exc

    if not os.path.exists(path):
        raise FileNotFoundError(f"Prompt injection config not found: {path}")
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle.read())
    if not isinstance(data, dict) or "detection_patterns" not in data:
        raise ValueError("YAML file must contain a 'detection_patterns' section")

    patterns = data["detection_patterns"] or {}
    return PromptInjectionConfig(
        direct_override_patterns=patterns.get("direct_override", [p.pattern for p in _DIRECT_OVERRIDE_PATTERNS]),
        delimiter_patterns=patterns.get("delimiter", [p.pattern for p in _DELIMITER_PATTERNS]),
        role_play_patterns=patterns.get("role_play", [p.pattern for p in _ROLE_PLAY_PATTERNS]),
        context_manipulation_patterns=patterns.get("context_manipulation", [p.pattern for p in _CONTEXT_MANIPULATION_PATTERNS]),
        multi_turn_patterns=patterns.get("multi_turn", [p.pattern for p in _MULTI_TURN_PATTERNS]),
        encoding_patterns=patterns.get("encoding", [p.pattern for p in _ENCODING_PATTERNS]),
        base64_pattern=patterns.get("base64_pattern", _BASE64_PATTERN.pattern),
        suspicious_decoded_keywords=data.get("suspicious_decoded_keywords", list(_SUSPICIOUS_DECODED_KEYWORDS)),
        sensitivity_thresholds=data.get("sensitivity_thresholds", dict(_SENSITIVITY_THRESHOLDS)),
        sensitivity_min_threat=data.get("sensitivity_min_threat", {k: v.value for k, v in _SENSITIVITY_MIN_THREAT.items()}),
    )


@dataclass(frozen=True)
class _Finding:
    injection_type: InjectionType
    threat_level: ThreatLevel
    confidence: float
    pattern: str
    span: tuple[int, int] | None = None


class PromptInjectionDetector:
    """Screens agent inputs for prompt injection attacks."""

    def __init__(
        self,
        config: DetectionConfig | None = None,
        pattern_config: PromptInjectionConfig | None = None,
    ) -> None:
        self._config = config or DetectionConfig()
        self._pattern_config = pattern_config or PromptInjectionConfig()
        self._patterns = _CompiledPatterns.from_config(self._pattern_config)
        self._audit_log: list[AuditRecord] = []

    def detect(
        self,
        text: str,
        source: str = "unknown",
        canary_tokens: list[str] | None = None,
    ) -> DetectionResult:
        """Scan text for injection patterns. Detection failures fail closed."""
        try:
            if text is None:
                raise ValueError("text must not be None")
            return self._detect_impl(str(text), source, canary_tokens)
        except Exception:
            result = DetectionResult(
                is_injection=True,
                threat_level=ThreatLevel.CRITICAL,
                injection_type=None,
                confidence=1.0,
                matched_patterns=["detection_error"],
                explanation="Detection error; input blocked fail-closed",
            )
            self._record_audit("" if text is None else str(text), source, result)
            return result

    def detect_batch(
        self,
        inputs: Sequence[tuple[str, str]],
        canary_tokens: list[str] | None = None,
    ) -> list[DetectionResult]:
        return [self.detect(text, source, canary_tokens) for text, source in inputs]

    @property
    def audit_log(self) -> list[AuditRecord]:
        return list(self._audit_log)

    def _detect_impl(
        self,
        text: str,
        source: str,
        canary_tokens: list[str] | None,
    ) -> DetectionResult:
        text_lower = text.lower()
        for blocked in self._config.blocklist:
            index = text_lower.find(blocked.lower())
            if index >= 0:
                finding = _Finding(
                    InjectionType.DIRECT_OVERRIDE,
                    ThreatLevel.HIGH,
                    1.0,
                    f"blocklist:{_short_hash(blocked)}",
                    (index, index + len(blocked)),
                )
                if not self._is_allowlisted(finding, text_lower):
                    result = self._result_from_findings([finding], "Input matched blocklist entry")
                    self._record_audit(text, source, result)
                    return result

        findings: list[_Finding] = []
        findings.extend(self._scan_regexes(text, self._patterns.direct_override, InjectionType.DIRECT_OVERRIDE, ThreatLevel.HIGH, 0.9, "direct_override"))
        findings.extend(self._scan_regexes(text, self._patterns.delimiter, InjectionType.DELIMITER_ATTACK, ThreatLevel.MEDIUM, 0.6, "delimiter"))
        findings.extend(self._scan_encoding(text))
        findings.extend(self._scan_regexes(text, self._patterns.role_play, InjectionType.ROLE_PLAY, ThreatLevel.HIGH, 0.85, "role_play"))
        findings.extend(self._scan_regexes(text, self._patterns.context_manipulation, InjectionType.CONTEXT_MANIPULATION, ThreatLevel.MEDIUM, 0.8, "context_manipulation"))
        findings.extend(self._scan_canaries(text, canary_tokens))
        findings.extend(self._scan_regexes(text, self._patterns.multi_turn, InjectionType.MULTI_TURN_ESCALATION, ThreatLevel.MEDIUM, 0.75, "multi_turn"))
        for pattern in self._config.custom_patterns:
            for match in pattern.finditer(text):
                findings.append(_Finding(InjectionType.DIRECT_OVERRIDE, ThreatLevel.HIGH, 0.8, f"custom:{pattern.pattern}", match.span()))

        threshold = _SENSITIVITY_THRESHOLDS[self._config.sensitivity]
        min_threat = _SENSITIVITY_MIN_THREAT[self._config.sensitivity]
        filtered = [
            finding
            for finding in findings
            if finding.confidence >= threshold and _THREAT_ORDER[finding.threat_level] >= _THREAT_ORDER[min_threat]
        ]
        filtered = [finding for finding in filtered if not self._is_allowlisted(finding, text_lower)]

        if not filtered:
            result = DetectionResult(
                is_injection=False,
                threat_level=ThreatLevel.NONE,
                injection_type=None,
                confidence=0.0,
                explanation="No injection patterns detected",
            )
        else:
            result = self._result_from_findings(filtered, "Prompt injection patterns detected")
        self._record_audit(text, source, result)
        return result

    def _result_from_findings(self, findings: list[_Finding], explanation: str) -> DetectionResult:
        highest = max(
            findings,
            key=lambda finding: (_THREAT_ORDER[finding.threat_level], finding.confidence),
        )
        return DetectionResult(
            is_injection=True,
            threat_level=highest.threat_level,
            injection_type=highest.injection_type,
            confidence=max(finding.confidence for finding in findings),
            matched_patterns=sorted({finding.pattern for finding in findings}),
            explanation=explanation,
        )

    def _scan_regexes(
        self,
        text: str,
        patterns: list[re.Pattern[str]],
        injection_type: InjectionType,
        threat_level: ThreatLevel,
        confidence: float,
        prefix: str,
    ) -> list[_Finding]:
        findings: list[_Finding] = []
        for pattern in patterns:
            for match in pattern.finditer(text):
                findings.append(_Finding(injection_type, threat_level, confidence, f"{prefix}:{pattern.pattern}", match.span()))
        return findings

    def _scan_encoding(self, text: str) -> list[_Finding]:
        findings = self._scan_regexes(
            text,
            self._patterns.encoding,
            InjectionType.ENCODING_ATTACK,
            ThreatLevel.HIGH,
            0.8,
            "encoding",
        )
        for match in self._patterns.base64.finditer(text):
            candidate = match.group(0)
            try:
                decoded = base64.b64decode(candidate).decode("utf-8", errors="ignore").lower()
            except Exception:
                continue
            for keyword in self._pattern_config.suspicious_decoded_keywords:
                if keyword.lower() in decoded:
                    findings.append(
                        _Finding(
                            InjectionType.ENCODING_ATTACK,
                            ThreatLevel.HIGH,
                            0.85,
                            f"base64_payload:{_short_hash(keyword)}",
                            match.span(),
                        )
                    )
                    break
        return findings

    @staticmethod
    def _scan_canaries(text: str, canary_tokens: list[str] | None) -> list[_Finding]:
        if not canary_tokens:
            return []
        findings: list[_Finding] = []
        text_lower = text.lower()
        for token in canary_tokens:
            if not token:
                continue
            index = text_lower.find(token.lower())
            if index >= 0:
                findings.append(
                    _Finding(
                        InjectionType.CANARY_LEAK,
                        ThreatLevel.CRITICAL,
                        1.0,
                        f"canary_leak:{_short_hash(token)}",
                        (index, index + len(token)),
                    )
                )
        return findings

    def _is_allowlisted(self, finding: _Finding, text_lower: str) -> bool:
        if not self._config.allowlist or finding.span is None:
            return False
        start, end = finding.span
        for term in self._config.allowlist:
            term_lower = term.lower()
            index = text_lower.find(term_lower)
            while index >= 0:
                term_end = index + len(term_lower)
                if start < term_end and index < end:
                    return True
                index = text_lower.find(term_lower, index + 1)
        return False

    def _record_audit(self, text: str, source: str, result: DetectionResult) -> None:
        self._audit_log.append(
            AuditRecord(
                timestamp=datetime.now(timezone.utc),
                input_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                source=source,
                result=result,
            )
        )


@dataclass(frozen=True)
class _CompiledPatterns:
    direct_override: list[re.Pattern[str]]
    delimiter: list[re.Pattern[str]]
    role_play: list[re.Pattern[str]]
    context_manipulation: list[re.Pattern[str]]
    multi_turn: list[re.Pattern[str]]
    encoding: list[re.Pattern[str]]
    base64: re.Pattern[str]

    @classmethod
    def from_config(cls, config: PromptInjectionConfig) -> "_CompiledPatterns":
        return cls(
            direct_override=_compile_all(config.direct_override_patterns),
            delimiter=_compile_all(config.delimiter_patterns),
            role_play=_compile_all(config.role_play_patterns),
            context_manipulation=_compile_all(config.context_manipulation_patterns),
            multi_turn=_compile_all(config.multi_turn_patterns),
            encoding=_compile_all(config.encoding_patterns),
            base64=re.compile(config.base64_pattern),
        )


_DIRECT_OVERRIDE_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"new\s+role\s*:", re.IGNORECASE),
    re.compile(r"forget\s+(everything|all|your)\b", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(above|prior|previous)\b", re.IGNORECASE),
    re.compile(r"override\s+(previous\s+)?instructions", re.IGNORECASE),
    re.compile(r"do\s+not\s+follow\s+(your|the)\s+(previous\s+)?instructions", re.IGNORECASE),
]
_DELIMITER_PATTERNS = [
    re.compile(r"^-{3,}\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^#{3,}\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^```\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"END\s+SYSTEM", re.IGNORECASE),
    re.compile(r"BEGIN\s+USER", re.IGNORECASE),
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
    re.compile(r"<\|im_end\|>", re.IGNORECASE),
    re.compile(r"\[INST\]", re.IGNORECASE),
    re.compile(r"<<SYS>>", re.IGNORECASE),
    re.compile(r"<\|system\|>", re.IGNORECASE),
    re.compile(r"<\|user\|>", re.IGNORECASE),
    re.compile(r"<\|assistant\|>", re.IGNORECASE),
]
_ROLE_PLAY_PATTERNS = [
    re.compile(r"pretend\s+you\s+are", re.IGNORECASE),
    re.compile(r"act\s+as\s+if\s+you\s+have\s+no\s+restrictions", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
    re.compile(r"\bDAN\s+mode\b", re.IGNORECASE),
    re.compile(r"developer\s+mode\s+override", re.IGNORECASE),
    re.compile(r"bypass\s+(all\s+)?(safety|content)\s+(filters?|restrictions?)", re.IGNORECASE),
    re.compile(r"you\s+have\s+no\s+(limitations?|restrictions?|rules?)", re.IGNORECASE),
]
_CONTEXT_MANIPULATION_PATTERNS = [
    re.compile(r"the\s+above\s+instructions\s+are\s+wrong", re.IGNORECASE),
    re.compile(r"actually\s+your\s+real\s+instructions\s+are", re.IGNORECASE),
    re.compile(r"the\s+developer\s+told\s+me\s+to\s+tell\s+you", re.IGNORECASE),
    re.compile(r"secret\s+password\s+is", re.IGNORECASE),
    re.compile(r"your\s+true\s+purpose\s+is", re.IGNORECASE),
    re.compile(r"the\s+real\s+system\s+prompt\s+is", re.IGNORECASE),
]
_MULTI_TURN_PATTERNS = [
    re.compile(r"as\s+I\s+mentioned\s+before.*you\s+agreed\s+to", re.IGNORECASE),
    re.compile(r"you\s+already\s+said\s+yes", re.IGNORECASE),
    re.compile(r"continuing\s+from\s+where\s+you\s+unlocked", re.IGNORECASE),
    re.compile(r"you\s+previously\s+confirmed", re.IGNORECASE),
    re.compile(r"we\s+already\s+established\s+that\s+you\s+can", re.IGNORECASE),
]
_BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")
_ENCODING_PATTERNS = [
    re.compile(r"\\x[0-9a-fA-F]{2}(?:\\x[0-9a-fA-F]{2}){3,}", re.IGNORECASE),
    re.compile(r"\\u[0-9a-fA-F]{4}(?:\\u[0-9a-fA-F]{4}){3,}", re.IGNORECASE),
    re.compile(r"\brot13\b", re.IGNORECASE),
    re.compile(r"\bbase64\s*decode\b", re.IGNORECASE),
    re.compile(r"\bhex\s*decode\b", re.IGNORECASE),
]
_SUSPICIOUS_DECODED_KEYWORDS = [
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
]
_SENSITIVITY_THRESHOLDS = {"strict": 0.3, "balanced": 0.5, "permissive": 0.7}
_SENSITIVITY_MIN_THREAT = {
    "strict": ThreatLevel.LOW,
    "balanced": ThreatLevel.LOW,
    "permissive": ThreatLevel.HIGH,
}


def _compile_all(patterns: Sequence[str]) -> list[re.Pattern[str]]:
    return [re.compile(pattern, re.IGNORECASE) for pattern in patterns]


def _validate_terms(name: str, terms: Sequence[str]) -> tuple[str, ...]:
    validated: list[str] = []
    for term in terms:
        stripped = term.strip()
        if not stripped:
            raise ValueError(f"{name} entries must not be empty")
        if len(stripped) < _MIN_LIST_ENTRY_LENGTH:
            raise ValueError(f"{name} entry {term!r} is too short")
        validated.append(stripped)
    return tuple(validated)


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
