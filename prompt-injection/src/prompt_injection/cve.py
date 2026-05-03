# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""OSV-backed CVE checks for MCP server packages."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


OSV_API_URL = "https://api.osv.dev/v1/query"


@dataclass
class VulnerabilityRecord:
    """A known vulnerability affecting a package."""

    cve_id: str
    package: str
    version: str
    severity: str
    summary: str
    affected_versions: str = ""
    fixed_version: str = ""
    references: list[str] = field(default_factory=list)
    published: str | None = None
    source: str = "osv"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cve_id": self.cve_id,
            "package": self.package,
            "version": self.version,
            "severity": self.severity,
            "summary": self.summary,
            "affected_versions": self.affected_versions,
            "fixed_version": self.fixed_version,
            "references": list(self.references),
            "published": self.published,
            "source": self.source,
        }


@dataclass(frozen=True)
class PackageEntry:
    """Tracked package entry."""

    name: str
    version: str
    ecosystem: str = "npm"


class McpCveFeed:
    """Track known vulnerabilities in MCP server packages."""

    def __init__(self, cache_ttl_seconds: int = 3600, *, offline: bool = False) -> None:
        if cache_ttl_seconds < 0:
            raise ValueError("cache_ttl_seconds must be non-negative")
        self._packages: list[PackageEntry] = []
        self._cache: dict[str, list[VulnerabilityRecord]] = {}
        self._cache_time: dict[str, float] = {}
        self._cache_ttl = cache_ttl_seconds
        self._manual: list[VulnerabilityRecord] = []
        self.offline = offline

    def add_package(self, name: str, version: str, ecosystem: str = "npm") -> None:
        self._packages.append(PackageEntry(name=name, version=version, ecosystem=ecosystem))

    def remove_package(self, name: str) -> bool:
        before = len(self._packages)
        self._packages = [package for package in self._packages if package.name != name]
        return len(self._packages) < before

    @property
    def tracked_packages(self) -> list[PackageEntry]:
        return list(self._packages)

    def check_package(self, name: str, version: str, ecosystem: str = "npm") -> list[VulnerabilityRecord]:
        cache_key = self._cache_key(ecosystem, name, version)
        now = datetime.now(timezone.utc).timestamp()
        if cache_key in self._cache and now - self._cache_time.get(cache_key, 0) < self._cache_ttl:
            return list(self._cache[cache_key])
        vulnerabilities = [] if self.offline else self._query_osv(name, version, ecosystem)
        vulnerabilities.extend(
            record
            for record in self._manual
            if record.package == name and record.version == version
        )
        self._cache[cache_key] = vulnerabilities
        self._cache_time[cache_key] = now
        return list(vulnerabilities)

    def check_all(self) -> list[VulnerabilityRecord]:
        vulnerabilities: list[VulnerabilityRecord] = []
        for package in self._packages:
            vulnerabilities.extend(self.check_package(package.name, package.version, package.ecosystem))
        return vulnerabilities

    def has_critical(self) -> bool:
        return any(record.severity == "CRITICAL" for record in self.check_all())

    def summary(self) -> dict[str, int]:
        counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
        for record in self.check_all():
            counts[record.severity] = counts.get(record.severity, 0) + 1
        return counts

    def add_manual_advisory(self, record: VulnerabilityRecord) -> None:
        record.source = "manual"
        self._manual.append(record)
        for cache_key in list(self._cache):
            if cache_key.endswith(f":{record.package}:{record.version}"):
                self._cache.pop(cache_key, None)
                self._cache_time.pop(cache_key, None)

    def _query_osv(self, name: str, version: str, ecosystem: str) -> list[VulnerabilityRecord]:
        payload = json.dumps(
            {
                "version": version,
                "package": {
                    "name": name,
                    "ecosystem": ecosystem,
                },
            }
        ).encode("utf-8")
        try:
            request = urllib.request.Request(
                OSV_API_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            return self._parse_osv_response(data, name, version)
        except Exception:
            return []

    @staticmethod
    def _parse_osv_response(data: dict[str, Any], package: str, version: str) -> list[VulnerabilityRecord]:
        vulnerabilities: list[VulnerabilityRecord] = []
        for vulnerability in data.get("vulns", []):
            severity = _severity_from_osv(vulnerability)
            cve_id = str(vulnerability.get("id", ""))
            for alias in vulnerability.get("aliases", []):
                if str(alias).startswith("CVE-"):
                    cve_id = str(alias)
                    break
            fixed = ""
            affected_versions = ""
            for affected in vulnerability.get("affected", []):
                for item_range in affected.get("ranges", []):
                    for event in item_range.get("events", []):
                        if "fixed" in event:
                            fixed = str(event["fixed"])
                        if "introduced" in event:
                            affected_versions = str(event["introduced"])
            references = [
                str(reference.get("url"))
                for reference in vulnerability.get("references", [])
                if reference.get("url")
            ][:5]
            summary = str(vulnerability.get("summary", vulnerability.get("details", "")))[:500]
            vulnerabilities.append(
                VulnerabilityRecord(
                    cve_id=cve_id,
                    package=package,
                    version=version,
                    severity=severity,
                    summary=summary,
                    affected_versions=affected_versions,
                    fixed_version=fixed,
                    references=references,
                    published=vulnerability.get("published"),
                    source="osv",
                )
            )
        return vulnerabilities

    @staticmethod
    def _cache_key(ecosystem: str, name: str, version: str) -> str:
        return f"{ecosystem}:{name}:{version}"


def _severity_from_osv(vulnerability: dict[str, Any]) -> str:
    severity = "UNKNOWN"
    for item in vulnerability.get("severity", []):
        score_text = str(item.get("score", ""))
        if not score_text:
            continue
        try:
            score = float(score_text.split("/")[0]) if "/" in score_text else float(score_text)
        except (ValueError, IndexError):
            continue
        if score >= 9.0:
            return "CRITICAL"
        if score >= 7.0:
            severity = "HIGH"
        elif score >= 4.0 and severity not in {"HIGH"}:
            severity = "MEDIUM"
        elif severity == "UNKNOWN":
            severity = "LOW"
    return severity
