# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Configuration, policy, trust, version, and capability drift detection."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class DriftType(str, Enum):
    """Categories of multi-agent drift."""

    CONFIG_DRIFT = "config_drift"
    POLICY_DRIFT = "policy_drift"
    TRUST_DRIFT = "trust_drift"
    VERSION_DRIFT = "version_drift"
    CAPABILITY_DRIFT = "capability_drift"


@dataclass(frozen=True)
class DriftFinding:
    """A single drift finding."""

    drift_type: DriftType
    severity: str
    source: str
    target: str
    field: str
    expected: Any
    actual: Any
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "drift_type": self.drift_type.value,
            "severity": self.severity,
            "source": self.source,
            "target": self.target,
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
            "message": self.message,
        }


@dataclass(frozen=True)
class DriftReport:
    """Aggregate drift report."""

    findings: list[DriftFinding] = field(default_factory=list)
    scanned_at: str = ""
    sources_scanned: int = 0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [finding.to_dict() for finding in self.findings],
            "scanned_at": self.scanned_at,
            "sources_scanned": self.sources_scanned,
            "summary": self.summary,
        }


class DriftDetector:
    """Detect drift across agent configurations, policies, trust, and capabilities."""

    def compare_configs(
        self,
        source_config: dict[str, Any],
        target_config: dict[str, Any],
        label: str = "",
    ) -> list[DriftFinding]:
        source_label = f"{label}/source" if label else "source"
        target_label = f"{label}/target" if label else "target"
        findings: list[DriftFinding] = []
        source_flat = _flatten(source_config)
        target_flat = _flatten(target_config)
        for key in sorted(set(source_flat) | set(target_flat)):
            expected = source_flat.get(key)
            actual = target_flat.get(key)
            if expected != actual:
                findings.append(
                    DriftFinding(
                        drift_type=DriftType.CONFIG_DRIFT,
                        severity=self._config_severity(key, expected, actual),
                        source=source_label,
                        target=target_label,
                        field=key,
                        expected=expected,
                        actual=actual,
                        message=self._config_message(key, expected, actual),
                    )
                )
        return findings

    def compare_policies(
        self,
        source_policies: dict[str, Any],
        target_policies: dict[str, Any],
    ) -> list[DriftFinding]:
        findings: list[DriftFinding] = []
        source_flat = _flatten(source_policies)
        target_flat = _flatten(target_policies)
        for key in sorted(set(source_flat) | set(target_flat)):
            expected = source_flat.get(key)
            actual = target_flat.get(key)
            if expected == actual:
                continue
            severity = "critical" if expected is None or actual is None else "warning"
            findings.append(
                DriftFinding(
                    drift_type=DriftType.POLICY_DRIFT,
                    severity=severity,
                    source="source_policies",
                    target="target_policies",
                    field=key,
                    expected=expected,
                    actual=actual,
                    message=f"Policy '{key}' differs",
                )
            )
        return findings

    def compare_trust_scores(
        self,
        source_scores: dict[str, float],
        target_scores: dict[str, float],
        tolerance: float = 0.1,
    ) -> list[DriftFinding]:
        findings: list[DriftFinding] = []
        for agent in sorted(set(source_scores) | set(target_scores)):
            expected = source_scores.get(agent)
            actual = target_scores.get(agent)
            if expected is None or actual is None:
                findings.append(
                    DriftFinding(
                        drift_type=DriftType.TRUST_DRIFT,
                        severity="warning",
                        source="source_scores",
                        target="target_scores",
                        field=agent,
                        expected=expected,
                        actual=actual,
                        message=f"Trust score for '{agent}' missing on one side",
                    )
                )
                continue
            diff = abs(float(expected) - float(actual))
            if diff > tolerance:
                findings.append(
                    DriftFinding(
                        drift_type=DriftType.TRUST_DRIFT,
                        severity="critical" if diff > tolerance * 3 else "warning",
                        source="source_scores",
                        target="target_scores",
                        field=agent,
                        expected=expected,
                        actual=actual,
                        message=f"Trust score for '{agent}' drifted by {diff:.3f}",
                    )
                )
        return findings

    def compare_capabilities(
        self,
        source_capabilities: dict[str, list[str]],
        target_capabilities: dict[str, list[str]],
    ) -> list[DriftFinding]:
        findings: list[DriftFinding] = []
        for agent in sorted(set(source_capabilities) | set(target_capabilities)):
            expected = sorted(source_capabilities.get(agent, []))
            actual = sorted(target_capabilities.get(agent, []))
            if expected != actual:
                added = sorted(set(actual) - set(expected))
                removed = sorted(set(expected) - set(actual))
                severity = "critical" if added else "warning"
                findings.append(
                    DriftFinding(
                        drift_type=DriftType.CAPABILITY_DRIFT,
                        severity=severity,
                        source="source_capabilities",
                        target="target_capabilities",
                        field=agent,
                        expected=expected,
                        actual=actual,
                        message=f"Capabilities drifted for '{agent}' added={added} removed={removed}",
                    )
                )
        return findings

    def detect_version_drift(self, components: dict[str, str]) -> list[DriftFinding]:
        findings: list[DriftFinding] = []
        if not components:
            return findings
        groups: dict[str, dict[str, str]] = {}
        for name, version in components.items():
            prefix = name.split("/", 1)[0].split("-", 1)[0]
            groups.setdefault(prefix, {})[name] = version
        for prefix, members in sorted(groups.items()):
            versions = list(members.values())
            if len(set(versions)) <= 1:
                continue
            majority = sorted(set(versions), key=lambda version: (-versions.count(version), version))[0]
            for name, version in sorted(members.items()):
                if version != majority:
                    findings.append(
                        DriftFinding(
                            drift_type=DriftType.VERSION_DRIFT,
                            severity="warning",
                            source=prefix,
                            target=name,
                            field="version",
                            expected=majority,
                            actual=version,
                            message=f"Component '{name}' at version {version} differs from majority {majority}",
                        )
                    )
        return findings

    def scan(self, sources: list[dict[str, Any]]) -> DriftReport:
        findings: list[DriftFinding] = []
        for index in range(len(sources) - 1):
            source = sources[index]
            target = sources[index + 1]
            label = f"{source.get('label', f'src-{index}')}-vs-{target.get('label', f'src-{index + 1}')}"
            if "config" in source and "config" in target:
                findings.extend(self.compare_configs(source["config"], target["config"], label))
            if "policies" in source and "policies" in target:
                findings.extend(self.compare_policies(source["policies"], target["policies"]))
            if "trust_scores" in source and "trust_scores" in target:
                tolerance = float(source.get("trust_tolerance", target.get("trust_tolerance", 0.1)))
                findings.extend(self.compare_trust_scores(source["trust_scores"], target["trust_scores"], tolerance))
            if "capabilities" in source and "capabilities" in target:
                findings.extend(self.compare_capabilities(source["capabilities"], target["capabilities"]))

        all_components: dict[str, str] = {}
        for source in sources:
            all_components.update(source.get("components", {}))
        findings.extend(self.detect_version_drift(all_components))

        return DriftReport(
            findings=findings,
            scanned_at=datetime.now(timezone.utc).isoformat(),
            sources_scanned=len(sources),
            summary=_summary(findings),
        )

    def to_markdown(self, report: DriftReport) -> str:
        lines = [
            "# Drift Detection Report",
            "",
            f"**Scanned at:** {report.scanned_at}  ",
            f"**Sources scanned:** {report.sources_scanned}  ",
            f"**Summary:** {report.summary}",
            "",
        ]
        if not report.findings:
            lines.append("No drift detected.")
            return "\n".join(lines)
        lines.append("| Severity | Type | Field | Expected | Actual | Message |")
        lines.append("|----------|------|-------|----------|--------|---------|")
        for finding in report.findings:
            lines.append(
                f"| {finding.severity} | {finding.drift_type.value} | {finding.field} "
                f"| {_short(finding.expected)} | {_short(finding.actual)} | {finding.message} |"
            )
        return "\n".join(lines)

    @staticmethod
    def _config_severity(key: str, expected: Any, actual: Any) -> str:
        if expected is None or actual is None:
            return "critical"
        lowered = key.lower()
        if any(marker in lowered for marker in ("allowed_tools", "blocked_tools", "approval", "auth", "isolation")):
            return "warning"
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            if expected != 0 and abs(expected - actual) / abs(expected) > 0.5:
                return "warning"
        return "info"

    @staticmethod
    def _config_message(key: str, expected: Any, actual: Any) -> str:
        if expected is None:
            return f"Key '{key}' only in target"
        if actual is None:
            return f"Key '{key}' missing in target"
        return f"Key '{key}' differs"


def _flatten(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, dict):
            flattened.update(_flatten(item, path))
        else:
            flattened[path] = item
    return flattened


def _summary(findings: list[DriftFinding]) -> str:
    critical = sum(1 for finding in findings if finding.severity == "critical")
    warnings = sum(1 for finding in findings if finding.severity == "warning")
    info = sum(1 for finding in findings if finding.severity == "info")
    return f"{len(findings)} finding(s): {critical} critical, {warnings} warning, {info} info"


def _short(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, default=str)
    return text if len(text) <= 80 else text[:77] + "..."
