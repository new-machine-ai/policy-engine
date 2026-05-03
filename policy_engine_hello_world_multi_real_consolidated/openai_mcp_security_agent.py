"""OpenAI Agents SDK MCP security smoke test."""

from __future__ import annotations

from _shared import OPENAI_MODEL, print_banner
from mcp_security_agent_shared import run_mcp_security_smoke


def main() -> None:
    print_banner("OpenAI Agents SDK — MCP security")

    from agents import Agent

    agent = Agent(
        name="openai-mcp-security-agent",
        model=OPENAI_MODEL,
        instructions="Use MCP tools only after policy approval.",
    )
    run_mcp_security_smoke("openai_mcp_security", f"OpenAI Agent(name={agent.name!r})")


if __name__ == "__main__":
    main()

