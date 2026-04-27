"""Claude Agent SDK — UserPromptSubmit hook from policy_engine.

NOTE: cannot run inside another Claude Code session — the SDK refuses nested
sessions. Run from a regular shell with CLAUDECODE unset.
"""

import asyncio

from _shared import POLICY, step


async def main() -> None:
    step("claude", "Importing claude_agent_sdk and the policy_engine hook factory.")
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, query
    from policy_engine.adapters.claude import make_user_prompt_hook

    step("claude", "Building the gov_hook from POLICY via make_user_prompt_hook.")
    gov_hook = make_user_prompt_hook(POLICY)

    step("claude", "Constructing ClaudeAgentOptions(hooks={'UserPromptSubmit': [HookMatcher(...)]}).")
    opts = ClaudeAgentOptions(
        hooks={"UserPromptSubmit": [HookMatcher(hooks=[gov_hook])]}
    )

    step("claude", "query(prompt='Say hello.', options=opts) — async streaming.")
    async for msg in query(prompt="Say hello.", options=opts):
        if hasattr(msg, "result"):
            step("claude", "Final result message received:")
            print(msg.result)


if __name__ == "__main__":
    import _shared  # noqa: F401
    asyncio.run(main())
