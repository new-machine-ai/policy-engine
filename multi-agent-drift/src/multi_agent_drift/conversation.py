# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Conversation guardian for multi-agent drift and escalation detection."""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AlertAction(str, Enum):
    """Recommended action for a conversation alert."""

    NONE = "none"
    WARN = "warn"
    PAUSE = "pause"
    BREAK = "break"
    QUARANTINE = "quarantine"


class AlertSeverity(str, Enum):
    """Severity of a conversation alert."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ConversationGuardianConfig:
    """Tunable thresholds for conversation drift detection."""

    escalation_score_threshold: float = 0.6
    escalation_critical_threshold: float = 0.85
    max_retry_cycles: int = 3
    max_conversation_turns: int = 30
    loop_window_seconds: float = 300.0
    offensive_score_threshold: float = 0.5
    offensive_critical_threshold: float = 0.8
    composite_warn_threshold: float = 0.4
    composite_pause_threshold: float = 0.6
    composite_break_threshold: float = 0.8
    capture_transcript: bool = True
    max_transcript_entries: int = 10_000


@dataclass(frozen=True)
class TranscriptEntry:
    """A single hashed conversation audit record."""

    conversation_id: str
    sender: str
    receiver: str
    content_hash: str
    content_preview: str
    escalation_score: float
    offensive_score: float
    loop_score: float
    action: str
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "sender": self.sender,
            "receiver": self.receiver,
            "content_hash": self.content_hash,
            "content_preview": self.content_preview,
            "escalation_score": round(self.escalation_score, 4),
            "offensive_score": round(self.offensive_score, 4),
            "loop_score": round(self.loop_score, 4),
            "action": self.action,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class ConversationAlert:
    """Result of analyzing a message in an agent-to-agent conversation."""

    conversation_id: str
    sender: str
    receiver: str
    severity: AlertSeverity
    action: AlertAction
    escalation_score: float
    offensive_score: float
    loop_score: float
    composite_score: float
    reasons: list[str] = field(default_factory=list)
    matched_patterns: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "sender": self.sender,
            "receiver": self.receiver,
            "severity": self.severity.value,
            "action": self.action.value,
            "escalation_score": round(self.escalation_score, 4),
            "offensive_score": round(self.offensive_score, 4),
            "loop_score": round(self.loop_score, 4),
            "composite_score": round(self.composite_score, 4),
            "reasons": list(self.reasons),
            "matched_patterns": list(self.matched_patterns),
            "timestamp": self.timestamp,
        }


_LEET_MAP = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_ESCALATION_PATTERNS: tuple[tuple[float, re.Pattern[str]], ...] = (
    (0.25, re.compile(r"\byou\s+must\b|\bdirect\s+order\b|\bno\s+excuses\b", re.IGNORECASE)),
    (0.30, re.compile(r"\bdo\s+whatever\s+it\s+takes\b|\bby\s+any\s+means\b", re.IGNORECASE)),
    (0.35, re.compile(r"\bbypass\b.*\b(?:control|security|restriction|auth)", re.IGNORECASE)),
    (0.35, re.compile(r"\bexploit\b.*\b(?:vulnerabilit\w*|weakness|flaw)", re.IGNORECASE)),
    (0.20, re.compile(r"\burgent\b|\bemergency\b|\bimmediately\b", re.IGNORECASE)),
)
_OFFENSIVE_PATTERNS: tuple[tuple[float, re.Pattern[str]], ...] = (
    (0.35, re.compile(r"\b(?:CVE|exploit|vulnerability|zero[- ]?day)\b", re.IGNORECASE)),
    (0.35, re.compile(r"\bescalate\s+privilege|\badmin\s+access|\broot\s+access", re.IGNORECASE)),
    (0.40, re.compile(r"\bexfiltrat\w*|\bcovert\s+channel|\bdns\s+(?:tunnel|exfil)", re.IGNORECASE)),
    (0.25, re.compile(r"\bscan\b.*\b(?:network|port|service)|\bnmap\b|\bsqlmap\b", re.IGNORECASE)),
    (0.35, re.compile(r"\b(?:SQL|command|OS)\s+injection\b|\bRCE\b|\bremote\s+code\s+execution\b", re.IGNORECASE)),
)
_ERROR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\baccess\s+denied\b|\bpermission\s+denied\b|\bforbidden\b", re.IGNORECASE),
    re.compile(r"\b401\b|\b403\b|\bunauthorized\b|\brestricted\b", re.IGNORECASE),
    re.compile(r"\bcannot\s+(?:access|read|write|execute)\b", re.IGNORECASE),
)


def normalize_text(text: str) -> str:
    """Normalize text to catch common evasion techniques."""
    text = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.translate(_LEET_MAP)
    return re.sub(r"\s+", " ", text).strip()


class EscalationClassifier:
    """Detect escalating rhetoric in agent-to-agent messages."""

    def __init__(self) -> None:
        self._history: dict[str, list[tuple[float, float]]] = defaultdict(list)

    def analyze(self, conversation_id: str, text: str, timestamp: float) -> tuple[float, list[str]]:
        score, patterns = _score(text, _ESCALATION_PATTERNS)
        self._history[conversation_id].append((timestamp, score))
        recent = self._history[conversation_id][-10:]
        if len(recent) < 2:
            return score, patterns
        weights = list(range(1, len(recent) + 1))
        trend = sum(weight * item_score for weight, (_, item_score) in zip(weights, recent)) / sum(weights)
        return max(score, trend), patterns


class OffensiveIntentDetector:
    """Detect offensive cyber-operation planning language."""

    def score_message(self, text: str) -> tuple[float, list[str]]:
        return _score(text, _OFFENSIVE_PATTERNS)


@dataclass
class _ConversationState:
    turn_count: int = 0
    retry_count: int = 0
    error_retry_streak: int = 0
    last_error_turn: int = -1
    escalation_scores: list[float] = field(default_factory=list)

    @property
    def escalation_trend(self) -> float:
        scores = self.escalation_scores[-6:]
        if len(scores) < 3:
            return 0.0
        middle = len(scores) // 2
        earlier = sum(scores[:middle]) / middle
        later = sum(scores[middle:]) / (len(scores) - middle)
        return max(0.0, later - earlier)


class FeedbackLoopBreaker:
    """Detect retry/escalation loops across a conversation."""

    def __init__(self, max_retry_cycles: int = 3, max_conversation_turns: int = 30) -> None:
        self.max_retry_cycles = max_retry_cycles
        self.max_conversation_turns = max_conversation_turns
        self._states: dict[str, _ConversationState] = {}

    def record_message(self, conversation_id: str, text: str, escalation_score: float) -> float:
        state = self._states.setdefault(conversation_id, _ConversationState())
        state.turn_count += 1
        state.escalation_scores.append(escalation_score)
        if any(pattern.search(text) for pattern in _ERROR_PATTERNS):
            state.retry_count += 1
            if state.last_error_turn == state.turn_count - 1:
                state.error_retry_streak += 1
            else:
                state.error_retry_streak = 1
            state.last_error_turn = state.turn_count
        return self.score(conversation_id)

    def score(self, conversation_id: str) -> float:
        state = self._states.get(conversation_id)
        if state is None:
            return 0.0
        turn_component = min((state.turn_count / self.max_conversation_turns) * 0.3, 0.3)
        retry_component = min((state.retry_count / self.max_retry_cycles) * 0.4, 0.4)
        trend_component = min(state.escalation_trend * 0.6, 0.3)
        return min(turn_component + retry_component + trend_component, 1.0)

    def should_break(self, conversation_id: str) -> tuple[bool, str]:
        state = self._states.get(conversation_id)
        if state is None:
            return False, ""
        if state.turn_count >= self.max_conversation_turns:
            return True, "max_conversation_turns_exceeded"
        if state.retry_count >= self.max_retry_cycles:
            return True, "max_retry_cycles_exceeded"
        if state.error_retry_streak >= self.max_retry_cycles:
            return True, "consecutive_error_retry_streak"
        return False, ""


class ConversationGuardian:
    """Composite conversation guardian for multi-agent drift detection."""

    def __init__(self, config: ConversationGuardianConfig | None = None) -> None:
        self.config = config or ConversationGuardianConfig()
        self.escalation_classifier = EscalationClassifier()
        self.offensive_detector = OffensiveIntentDetector()
        self.loop_breaker = FeedbackLoopBreaker(
            max_retry_cycles=self.config.max_retry_cycles,
            max_conversation_turns=self.config.max_conversation_turns,
        )
        self._alerts: list[ConversationAlert] = []
        self._transcript: list[TranscriptEntry] = []

    def analyze_message(
        self,
        conversation_id: str,
        sender: str,
        receiver: str,
        content: str,
        timestamp: float | None = None,
    ) -> ConversationAlert:
        ts = timestamp or time.time()
        escalation_score, escalation_patterns = self.escalation_classifier.analyze(conversation_id, content, ts)
        offensive_score, offensive_patterns = self.offensive_detector.score_message(content)
        loop_score = self.loop_breaker.record_message(conversation_id, content, escalation_score)
        should_break, break_reason = self.loop_breaker.should_break(conversation_id)

        composite = max(escalation_score, offensive_score, loop_score)
        reasons: list[str] = []
        if escalation_score >= self.config.escalation_score_threshold:
            reasons.append("escalation_detected")
        if offensive_score >= self.config.offensive_score_threshold:
            reasons.append("offensive_intent_detected")
        if loop_score >= self.config.composite_pause_threshold:
            reasons.append("feedback_loop_detected")
        if should_break:
            reasons.append(break_reason)
            composite = max(composite, self.config.composite_break_threshold)

        severity, action = self._severity_action(composite, should_break)
        alert = ConversationAlert(
            conversation_id=conversation_id,
            sender=sender,
            receiver=receiver,
            severity=severity,
            action=action,
            escalation_score=escalation_score,
            offensive_score=offensive_score,
            loop_score=loop_score,
            composite_score=composite,
            reasons=reasons,
            matched_patterns=escalation_patterns + offensive_patterns,
            timestamp=ts,
        )
        self._alerts.append(alert)
        self._record_transcript(alert, content)
        return alert

    @property
    def alerts(self) -> list[ConversationAlert]:
        return list(self._alerts)

    @property
    def transcript(self) -> list[TranscriptEntry]:
        return list(self._transcript)

    def _severity_action(self, composite: float, should_break: bool) -> tuple[AlertSeverity, AlertAction]:
        if should_break or composite >= self.config.composite_break_threshold:
            return AlertSeverity.CRITICAL, AlertAction.BREAK
        if composite >= self.config.composite_pause_threshold:
            return AlertSeverity.HIGH, AlertAction.PAUSE
        if composite >= self.config.composite_warn_threshold:
            return AlertSeverity.MEDIUM, AlertAction.WARN
        if composite > 0:
            return AlertSeverity.LOW, AlertAction.NONE
        return AlertSeverity.NONE, AlertAction.NONE

    def _record_transcript(self, alert: ConversationAlert, content: str) -> None:
        if not self.config.capture_transcript:
            return
        if len(self._transcript) >= self.config.max_transcript_entries:
            self._transcript.pop(0)
        self._transcript.append(
            TranscriptEntry(
                conversation_id=alert.conversation_id,
                sender=alert.sender,
                receiver=alert.receiver,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                content_preview=normalize_text(content)[:80],
                escalation_score=alert.escalation_score,
                offensive_score=alert.offensive_score,
                loop_score=alert.loop_score,
                action=alert.action.value,
                timestamp=alert.timestamp,
            )
        )


def _score(text: str, patterns: tuple[tuple[float, re.Pattern[str]], ...]) -> tuple[float, list[str]]:
    normalized = normalize_text(text)
    total = 0.0
    matched: list[str] = []
    for weight, pattern in patterns:
        if pattern.search(text) or pattern.search(normalized):
            total += weight
            matched.append(pattern.pattern)
    return min(total, 1.0), matched

