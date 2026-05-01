"""Real OpenAI Agents SDK hello-world agent governed by policy-engine."""

from __future__ import annotations

import asyncio

from _shared import OPENAI_AGENTS_POLICY, OPENAI_MODEL, PROMPT, print_banner, require_env


async def main() -> None:
    require_env("OPENAI_API_KEY")
    print_banner("OpenAI Agents SDK")

    from agents import Agent, Runner

    from policy_engine.adapters.openai_agents import OpenAIAgentsKernel

    kernel = OpenAIAgentsKernel(policy=OPENAI_AGENTS_POLICY)
    agent = Agent(
        name="assistant",
        model=OPENAI_MODEL,
        instructions="Be friendly and concise.",
    )
    governed = kernel.wrap(agent)
    governed_runner = kernel.wrap_runner(Runner)
    result = await governed_runner.run(governed, PROMPT)
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
