"""Real Microsoft Agent Framework hello-world agent governed by policy-engine."""

from __future__ import annotations

import asyncio

from _shared import MAF_POLICY, OPENAI_MODEL, PROMPT, print_banner, require_env


async def main() -> None:
    require_env("OPENAI_API_KEY")
    print_banner("Microsoft Agent Framework")

    from agent_framework import Agent
    from agent_framework.openai import OpenAIChatClient

    from policy_engine.adapters.maf import MAFKernel

    middleware = MAFKernel(MAF_POLICY).as_middleware(agent_id="hello-world-maf")
    async with Agent(
        client=OpenAIChatClient(model=OPENAI_MODEL),
        name="hello-world-maf",
        instructions="Be friendly.",
        middleware=middleware,
    ) as agent:
        response = await agent.run(PROMPT)
        print(getattr(response, "text", response))


if __name__ == "__main__":
    asyncio.run(main())
