"""Real OpenAI Agents SDK hello-world agent governed by policy-engine."""

from __future__ import annotations

import asyncio

from _shared import OPENAI_AGENTS_POLICY, OPENAI_MODEL, PROMPT, print_banner, require_env


async def main() -> None:
    require_env("OPENAI_API_KEY")
    print_banner("OpenAI Agents SDK")

    from agents import Agent, Runner

    from policy_engine.adapters.openai_agents import OpenAIAgentsKernel

    runner = OpenAIAgentsKernel(OPENAI_AGENTS_POLICY).wrap_runner(Runner)
    agent = Agent(name="assistant", model=OPENAI_MODEL, instructions="Be friendly and concise.")
    result = await runner.run(agent, PROMPT)
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
