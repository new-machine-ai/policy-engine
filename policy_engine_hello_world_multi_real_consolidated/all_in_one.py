"""Run all five live hello-world samples in one Python process."""

from __future__ import annotations

import asyncio

from anthropic_agent import main as run_anthropic
from claude_agent_sdk_agent import main as run_claude_agent_sdk
from langchain_agent import main as run_langchain
from microsoft_agent import main as run_microsoft
from openai_agent import main as run_openai_agents


async def main() -> None:
    run_langchain()
    await run_openai_agents()
    await run_microsoft()
    run_anthropic()
    await run_claude_agent_sdk()


if __name__ == "__main__":
    asyncio.run(main())
