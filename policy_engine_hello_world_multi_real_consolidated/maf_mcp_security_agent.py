"""Microsoft Agent Framework MCP security smoke test."""

from __future__ import annotations

from _shared import print_banner
from mcp_security_agent_shared import MCP_SECURITY_POLICY, run_mcp_security_smoke


def main() -> None:
    print_banner("Microsoft Agent Framework — MCP security")

    from agent_framework import Agent

    from policy_engine.adapters.maf import MAFKernel

    middleware = MAFKernel(MCP_SECURITY_POLICY).as_middleware(
        agent_id="maf-mcp-security-agent"
    )
    run_mcp_security_smoke(
        "maf_mcp_security",
        f"{Agent.__name__}(middleware={len(middleware)} policy hooks)",
    )


if __name__ == "__main__":
    main()

