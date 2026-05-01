"""Real Claude Agent SDK hello-world governed by policy-engine hooks."""

from __future__ import annotations

import asyncio

from _shared import CLAUDE_AGENT_SDK_POLICY, PROMPT, print_banner, require_env


async def prompt_stream():
    yield {
        "type": "user",
        "message": {"role": "user", "content": PROMPT},
        "parent_tool_use_id": None,
        "session_id": "hello",
    }


async def main() -> None:
    require_env("ANTHROPIC_API_KEY")
    print_banner("Claude Agent SDK")

    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, HookMatcher, query

    from policy_engine.adapters.claude import (
        make_pre_tool_use_hook,
        make_user_prompt_hook,
    )
    from policy_engine.kernel import BaseKernel

    kernel = BaseKernel(CLAUDE_AGENT_SDK_POLICY)
    ctx = kernel.create_context("hello-world-claude-agent-sdk")
    options = ClaudeAgentOptions(
        allowed_tools=[],
        system_prompt="Be friendly and concise.",
        hooks={
            "UserPromptSubmit": [
                HookMatcher(
                    hooks=[
                        make_user_prompt_hook(
                            CLAUDE_AGENT_SDK_POLICY,
                            kernel=kernel,
                            ctx=ctx,
                        )
                    ]
                )
            ],
            "PreToolUse": [
                HookMatcher(
                    hooks=[
                        make_pre_tool_use_hook(
                            CLAUDE_AGENT_SDK_POLICY,
                            kernel=kernel,
                            ctx=ctx,
                        )
                    ]
                )
            ],
        },
    )

    async for message in query(prompt=prompt_stream(), options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                text = getattr(block, "text", None)
                if text:
                    print(text)


if __name__ == "__main__":
    asyncio.run(main())
