"""Real Claude Agent SDK hello-world governed by policy-engine."""

from __future__ import annotations

import asyncio

from _shared import (
    CLAUDE_AGENT_SDK_POLICY,
    PROMPT,
    claude_prompt_stream,
    print_banner,
    require_env,
)


async def main() -> None:
    require_env("ANTHROPIC_API_KEY")
    print_banner("Claude Agent SDK")

    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, query

    from policy_engine.adapters.claude import ClaudeSDKKernel

    options = ClaudeSDKKernel(CLAUDE_AGENT_SDK_POLICY).governed_options(
        ClaudeAgentOptions(allowed_tools=[], system_prompt="Be friendly and concise.")
    )
    async for message in query(prompt=claude_prompt_stream(PROMPT), options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                text = getattr(block, "text", None)
                if text:
                    print(text)


if __name__ == "__main__":
    asyncio.run(main())
