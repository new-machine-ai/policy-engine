"""GovernancePolicy + policy decision types. Pure stdlib."""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Literal

from policy_engine.rate_limit import RateLimitConfig

PatternEngine = Literal["substring", "regex"]


@dataclass(frozen=True)
class PolicyRequest:
    payload: str = ""
    tool_name: str | None = None
    phase: str = "pre_execute"

    def payload_sha256(self) -> str:
        return hashlib.sha256((self.payload or "").encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str | None = None
    policy: str = ""
    matched_pattern: str | None = None
    tool_name: str | None = None
    requires_approval: bool = False
    payload_hash: str = ""
    phase: str = "pre_execute"


@dataclass
class GovernancePolicy:
    name: str = "default"
    blocked_patterns: list[str] = field(default_factory=list)
    max_tool_calls: int = 10
    require_human_approval: bool = False
    allowed_tools: list[str] | None = None
    blocked_tools: list[str] | None = None
    rate_limit: RateLimitConfig | None = None
    pattern_engine: PatternEngine = "substring"
    audit_payload_summary: int = 0

    def validate(self) -> None:
        if self.max_tool_calls < 0:
            raise ValueError("max_tool_calls must be >= 0")
        for pattern in self.blocked_patterns:
            if not pattern or not pattern.strip():
                raise ValueError("blocked_patterns must not contain blank entries")
        if self.allowed_tools is not None and self.blocked_tools is not None:
            overlap = set(self.allowed_tools).intersection(self.blocked_tools)
            if overlap:
                names = ", ".join(sorted(overlap))
                raise ValueError(f"tools cannot be both allowed and blocked: {names}")
        if self.pattern_engine not in ("substring", "regex"):
            raise ValueError(
                f"pattern_engine must be 'substring' or 'regex', got {self.pattern_engine!r}"
            )
        if self.pattern_engine == "regex":
            for pattern in self.blocked_patterns:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise ValueError(f"invalid regex {pattern!r}: {exc}") from exc
        if self.audit_payload_summary < 0:
            raise ValueError("audit_payload_summary must be >= 0")

    def matches_pattern(self, text: str) -> str | None:
        if not text:
            return None
        if self.pattern_engine == "regex":
            for pattern in self.blocked_patterns:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    return pattern
            return None
        haystack = text.casefold()
        for pattern in self.blocked_patterns:
            if pattern.casefold() in haystack:
                return pattern
        return None


class PolicyViolationError(Exception):
    def __init__(self, reason: str, pattern: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.pattern = pattern
