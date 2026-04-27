"""MAF — middleware list from policy_engine.adapters.maf."""

import asyncio
import os

from _shared import POLICY, audit, step


async def main() -> None:
    step("maf", "Importing MAF Agent + OpenAIChatClient and the policy_engine MAF adapter.")
    from agent_framework import Agent
    from agent_framework.openai import OpenAIChatClient
    from policy_engine.adapters.maf import create_governance_middleware

    step("maf", f"Shared policy: {POLICY.name} (blocked_patterns={POLICY.blocked_patterns}, "
                f"max_tool_calls={POLICY.max_tool_calls}).")

    step("maf", "Building the MAF middleware stack via create_governance_middleware().")
    stack = create_governance_middleware(
        allowed_tools=None,
        denied_tools=None,
        agent_id="policy-engine-maf",
        enable_rogue_detection=False,
    )
    step("maf", f"Stack built with {len(stack)} middleware layer(s).")
    audit("maf", "stack_built", "ALLOWED", f"layers={len(stack)}")

    model = (
        os.environ.get("OPENAI_MODEL")
        or os.environ.get("OPENAI_CHAT_MODEL")
        or "gpt-4o-mini"
    )
    step("maf", f"Resolved chat model: {model}.")

    step("maf", "Constructing Agent(client=OpenAIChatClient, middleware=stack).")
    async with Agent(
        client=OpenAIChatClient(model=model),
        name="policy-engine-maf",
        instructions="Reply briefly.",
        middleware=stack,
    ) as a:
        step("maf", "Calling agent.run('Say hello.').")
        result = await a.run("Say hello.")
        audit("maf", "on_agent_end", "ALLOWED", f"{len(result.text)}ch")
        step("maf", "Final model output:")
        print(result.text)


if __name__ == "__main__":
    import _shared  # noqa: F401
    asyncio.run(main())
