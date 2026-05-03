# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Compatibility imports for MCP scanners from the sibling package."""

from __future__ import annotations

try:
    from mcp_security_scanner import (
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
except ImportError as exc:  # pragma: no cover - exercised only without installed sibling package
    raise ImportError(
        "prompt-injection requires mcp-security-scanner for MCP compatibility. "
        "Install it with `pip install -e ./mcp-security-scanner` from this checkout."
    ) from exc


__all__ = [
    "MCPResponseScanResult",
    "MCPResponseScanner",
    "MCPResponseThreat",
    "MCPSecurityScanner",
    "MCPSeverity",
    "MCPThreat",
    "MCPThreatType",
    "ScanResult",
    "ToolFingerprint",
]
