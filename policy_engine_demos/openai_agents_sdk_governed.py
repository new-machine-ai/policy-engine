"""OpenAI Agents SDK — OpenAIAgentsKernel + wrapped Runner."""

import asyncio

from _shared import POLICY, audit, step


async def main() -> None:
    step("openai_agents", "Importing the OpenAI Agents SDK and policy_engine adapter.")
    from agents import Agent, Runner, RunHooks
    from policy_engine.adapters.openai_agents import (
        GovernancePolicy as OAIPolicy,
        OpenAIAgentsKernel,
        PolicyViolationError,
    )

    step("openai_agents", "Constructing OpenAIAgentsKernel with adapter-specific policy "
                          "(adds tool allow/deny on top of blocked_patterns).")
    kernel = OpenAIAgentsKernel(
        policy=OAIPolicy(
            allowed_tools=[],
            blocked_tools=["shell_exec", "network_request"],
            blocked_patterns=POLICY.blocked_patterns,
            max_tool_calls=POLICY.max_tool_calls,
        ),
        on_violation=lambda e: audit("openai_agents", "violation", "BLOCKED", str(e)),
    )

    step("openai_agents", "Defining GovernedHooks(RunHooks).")
    class GovernedHooks(RunHooks):
        async def on_agent_start(self, context, agent):
            audit("openai_agents", "on_agent_start", "ALLOWED", agent.name)

        async def on_agent_end(self, context, agent, output):
            audit("openai_agents", "on_agent_end", "ALLOWED", f"{len(str(output))}ch")

    step("openai_agents", "Creating a raw Agent and wrapping it.")
    raw_agent = Agent(name="policy-engine-oai", instructions="Reply briefly.")
    governed = kernel.wrap(raw_agent)

    step("openai_agents", "Wrapping Runner via kernel.wrap_runner(Runner).")
    GovernedRunner = kernel.wrap_runner(Runner)

    try:
        step("openai_agents", "GovernedRunner.run(governed, 'Say hello.', hooks=GovernedHooks()).")
        result = await GovernedRunner.run(governed, "Say hello.", hooks=GovernedHooks())
        step("openai_agents", "Final agent output:")
        print(result.final_output)
    except PolicyViolationError as e:
        audit("openai_agents", "run", "BLOCKED", str(e))


if __name__ == "__main__":
    import _shared  # noqa: F401
    asyncio.run(main())
