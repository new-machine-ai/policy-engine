# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""LlamaFirewall integration adapter with local detector fallback."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .detector import DetectionConfig, DetectionResult, PromptInjectionDetector, ThreatLevel


class FirewallMode(str, Enum):
    """Operating mode for combined prompt scanning."""

    LLAMAFIREWALL_ONLY = "llamafirewall_only"
    AGENT_OS_ONLY = "agent_os_only"
    CHAIN_BOTH = "chain_both"
    VOTE_MAJORITY = "vote_majority"


class FirewallVerdict(str, Enum):
    """Unified scanner verdict."""

    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    BLOCKED = "blocked"
    ERROR = "error"


@dataclass(frozen=True)
class FirewallResult:
    """Combined result from LlamaFirewall and local prompt scanning."""

    verdict: FirewallVerdict
    source: str
    score: float
    details: dict[str, Any] = field(default_factory=dict)
    prompt_guard_result: dict[str, Any] | None = None
    alignment_check_result: dict[str, Any] | None = None
    code_shield_result: dict[str, Any] | None = None
    local_result: DetectionResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "source": self.source,
            "score": round(self.score, 4),
            "details": dict(self.details),
            "prompt_guard_result": self.prompt_guard_result,
            "alignment_check_result": self.alignment_check_result,
            "code_shield_result": self.code_shield_result,
            "local_result": self.local_result.to_dict() if self.local_result else None,
        }


class LlamaFirewallAdapter:
    """Chain optional LlamaFirewall checks with the local prompt detector."""

    def __init__(
        self,
        mode: FirewallMode = FirewallMode.CHAIN_BOTH,
        local_config: DetectionConfig | None = None,
    ) -> None:
        self._mode = mode
        self._detector = PromptInjectionDetector(config=local_config)
        self._llama_available = self._check_llama_available()
        if mode == FirewallMode.LLAMAFIREWALL_ONLY and not self._llama_available:
            self._mode = FirewallMode.AGENT_OS_ONLY

    async def scan_prompt(self, prompt: str, context: str | None = None) -> FirewallResult:
        return self.scan_prompt_sync(prompt, context)

    def scan_prompt_sync(self, prompt: str, context: str | None = None) -> FirewallResult:
        mode = self._mode
        if mode == FirewallMode.AGENT_OS_ONLY:
            local_result = self._run_local_detector(prompt)
            return self._combine_results(None, local_result, mode)
        if mode == FirewallMode.LLAMAFIREWALL_ONLY:
            llama_result = self._run_llamafirewall(prompt, context)
            return self._combine_results(llama_result, None, mode)
        llama_result = self._run_llamafirewall(prompt, context) if self._llama_available else None
        local_result = self._run_local_detector(prompt)
        return self._combine_results(llama_result, local_result, mode)

    async def scan_code(self, code: str, language: str = "python") -> FirewallResult:
        if not self._llama_available:
            return FirewallResult(
                verdict=FirewallVerdict.SAFE,
                source="local",
                score=0.0,
                details={"warning": "CodeShield not available; llamafirewall is not installed"},
            )
        try:
            from llamafirewall import CodeShield  # type: ignore[import-not-found]
            result = CodeShield().scan(code, language=language)
            verdict = self._map_llama_verdict(str(result.get("verdict", "safe")))
            return FirewallResult(
                verdict=verdict,
                source="llamafirewall",
                score=float(result.get("score", 0.0)),
                details={"language": language},
                code_shield_result=result,
            )
        except Exception as exc:
            return FirewallResult(
                verdict=FirewallVerdict.ERROR,
                source="llamafirewall",
                score=0.0,
                details={"error": str(exc)},
            )

    @property
    def available_scanners(self) -> list[str]:
        scanners: list[str] = []
        if self._mode in {FirewallMode.AGENT_OS_ONLY, FirewallMode.CHAIN_BOTH, FirewallMode.VOTE_MAJORITY}:
            scanners.append("local_detector")
        if self._llama_available and self._mode in {
            FirewallMode.LLAMAFIREWALL_ONLY,
            FirewallMode.CHAIN_BOTH,
            FirewallMode.VOTE_MAJORITY,
        }:
            scanners.append("llamafirewall")
        return scanners

    @staticmethod
    def _check_llama_available() -> bool:
        try:
            import llamafirewall  # noqa: F401
        except ImportError:
            return False
        return True

    @staticmethod
    def _run_llamafirewall(prompt: str, context: str | None = None) -> dict[str, Any]:
        try:
            from llamafirewall import LlamaFirewall  # type: ignore[import-not-found]
            result = LlamaFirewall().scan(prompt, context=context)
            return {
                "verdict": result.get("verdict", "safe"),
                "score": float(result.get("score", 0.0)),
                "prompt_guard": result.get("prompt_guard"),
                "alignment_check": result.get("alignment_check"),
            }
        except ImportError:
            return {"verdict": "error", "score": 0.0, "error": "import_failed"}
        except Exception as exc:
            return {"verdict": "error", "score": 0.0, "error": str(exc)}

    def _run_local_detector(self, prompt: str) -> DetectionResult:
        return self._detector.detect(prompt, source="llamafirewall_adapter")

    def _combine_results(
        self,
        llama_result: dict[str, Any] | None,
        local_result: DetectionResult | None,
        mode: FirewallMode,
    ) -> FirewallResult:
        llama_score = float(llama_result.get("score", 0.0)) if llama_result else 0.0
        llama_verdict_text = str(llama_result.get("verdict", "safe")) if llama_result else "safe"
        llama_verdict = self._map_llama_verdict(llama_verdict_text)
        local_score = local_result.confidence if local_result else 0.0
        local_verdict = self._local_verdict(local_result) if local_result else FirewallVerdict.SAFE

        if mode == FirewallMode.AGENT_OS_ONLY:
            return FirewallResult(
                verdict=local_verdict,
                source="local_detector",
                score=local_score,
                details={"mode": mode.value},
                local_result=local_result,
            )
        if mode == FirewallMode.LLAMAFIREWALL_ONLY:
            return FirewallResult(
                verdict=llama_verdict,
                source="llamafirewall",
                score=llama_score,
                details={"mode": mode.value},
                prompt_guard_result=llama_result.get("prompt_guard") if llama_result else None,
                alignment_check_result=llama_result.get("alignment_check") if llama_result else None,
            )
        if mode == FirewallMode.CHAIN_BOTH:
            verdict = max(
                [llama_verdict, local_verdict],
                key=lambda item: _VERDICT_ORDER[item],
            )
            return FirewallResult(
                verdict=verdict,
                source="combined",
                score=max(llama_score, local_score),
                details={
                    "mode": mode.value,
                    "llama_verdict": llama_verdict.value,
                    "local_verdict": local_verdict.value,
                },
                prompt_guard_result=llama_result.get("prompt_guard") if llama_result else None,
                alignment_check_result=llama_result.get("alignment_check") if llama_result else None,
                local_result=local_result,
            )
        if mode == FirewallMode.VOTE_MAJORITY:
            block_votes = sum([llama_verdict == FirewallVerdict.BLOCKED, local_verdict == FirewallVerdict.BLOCKED])
            if block_votes >= 2:
                verdict = FirewallVerdict.BLOCKED
            elif block_votes == 1:
                verdict = FirewallVerdict.SUSPICIOUS
            else:
                verdict = FirewallVerdict.SAFE
            return FirewallResult(
                verdict=verdict,
                source="combined",
                score=(llama_score + local_score) / 2.0,
                details={
                    "mode": mode.value,
                    "block_votes": block_votes,
                    "llama_verdict": llama_verdict.value,
                    "local_verdict": local_verdict.value,
                },
                prompt_guard_result=llama_result.get("prompt_guard") if llama_result else None,
                alignment_check_result=llama_result.get("alignment_check") if llama_result else None,
                local_result=local_result,
            )
        return FirewallResult(
            verdict=FirewallVerdict.ERROR,
            source="combined",
            score=0.0,
            details={"error": f"unknown mode: {mode}"},
        )

    @staticmethod
    def _map_llama_verdict(verdict_text: str) -> FirewallVerdict:
        mapping = {
            "safe": FirewallVerdict.SAFE,
            "benign": FirewallVerdict.SAFE,
            "suspicious": FirewallVerdict.SUSPICIOUS,
            "blocked": FirewallVerdict.BLOCKED,
            "malicious": FirewallVerdict.BLOCKED,
            "error": FirewallVerdict.ERROR,
        }
        return mapping.get(verdict_text.lower(), FirewallVerdict.SUSPICIOUS)

    @staticmethod
    def _local_verdict(result: DetectionResult | None) -> FirewallVerdict:
        if result is None or not result.is_injection:
            return FirewallVerdict.SAFE
        if result.threat_level in {ThreatLevel.HIGH, ThreatLevel.CRITICAL}:
            return FirewallVerdict.BLOCKED
        return FirewallVerdict.SUSPICIOUS


_VERDICT_ORDER = {
    FirewallVerdict.SAFE: 0,
    FirewallVerdict.SUSPICIOUS: 1,
    FirewallVerdict.ERROR: 2,
    FirewallVerdict.BLOCKED: 3,
}
