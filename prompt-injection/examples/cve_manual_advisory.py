# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Offline CVE advisory example."""

from __future__ import annotations

from prompt_injection import McpCveFeed, VulnerabilityRecord


def main() -> None:
    feed = McpCveFeed(offline=True)
    feed.add_manual_advisory(
        VulnerabilityRecord(
            cve_id="CVE-2099-0001",
            package="mcp-server-demo",
            version="1.0.0",
            severity="CRITICAL",
            summary="Demo advisory for an unsafe MCP server package.",
            fixed_version="1.0.1",
        )
    )
    for record in feed.check_package("mcp-server-demo", "1.0.0"):
        print(record.to_dict())


if __name__ == "__main__":
    main()
