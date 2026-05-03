# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Prompt injection and untrusted-content defenses."""

from __future__ import annotations

from .cve import McpCveFeed, PackageEntry, VulnerabilityRecord
from .detector import (
    AuditRecord,
    DetectionConfig,
    DetectionResult,
    InjectionType,
    PromptInjectionConfig,
    PromptInjectionDetector,
    ThreatLevel,
    load_prompt_injection_config,
)
from .llamafirewall import FirewallMode, FirewallResult, FirewallVerdict, LlamaFirewallAdapter
from .mcp import (
    MCPResponseScanResult,
    MCPResponseScanner,
    MCPResponseThreat,
    MCPSecurityScanner,
    MCPSeverity,
    MCPThreat,
    MCPThreatType,
    ScanResult,
    ToolFingerprint,
)
from .signing import (
    InMemoryNonceStore,
    MCPMessageSigner,
    MCPNonceStore,
    MCPSignedEnvelope,
    MCPVerificationResult,
)

__all__ = [
    "AuditRecord",
    "DetectionConfig",
    "DetectionResult",
    "FirewallMode",
    "FirewallResult",
    "FirewallVerdict",
    "InMemoryNonceStore",
    "InjectionType",
    "LlamaFirewallAdapter",
    "MCPMessageSigner",
    "MCPNonceStore",
    "MCPResponseScanResult",
    "MCPResponseScanner",
    "MCPResponseThreat",
    "MCPSeverity",
    "MCPSecurityScanner",
    "MCPSignedEnvelope",
    "MCPThreat",
    "MCPThreatType",
    "MCPVerificationResult",
    "McpCveFeed",
    "PackageEntry",
    "PromptInjectionConfig",
    "PromptInjectionDetector",
    "ScanResult",
    "ThreatLevel",
    "ToolFingerprint",
    "VulnerabilityRecord",
    "load_prompt_injection_config",
]
