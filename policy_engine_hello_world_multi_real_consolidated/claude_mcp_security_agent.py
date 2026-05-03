"""Claude Agent SDK MCP security smoke test."""

from __future__ import annotations

from _shared import print_banner
from mcp_security_agent_shared import run_mcp_security_smoke


def main() -> None:
    print_banner("Claude Agent SDK — MCP security")

    from claude_agent_sdk import ClaudeAgentOptions

    options = ClaudeAgentOptions(
        allowed_tools=[],
        system_prompt="Use MCP tools only after policy approval.",
    )
    run_mcp_security_smoke(
        "claude_mcp_security",
        f"ClaudeAgentOptions(allowed_tools={list(options.allowed_tools or [])!r})",
    )


if __name__ == "__main__":
    main()

