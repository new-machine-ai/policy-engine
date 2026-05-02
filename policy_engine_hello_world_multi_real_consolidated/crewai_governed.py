"""CrewAI — before/after_llm_call decorators delegate to CrewAIKernel."""

import asyncio
import os

from _shared import POLICY, audit, step


async def main() -> None:
    step("crewai", "Importing CrewAI primitives and the policy_engine CrewAIKernel.")
    from crewai import Agent, Crew, Process, Task
    from crewai.hooks import (
        LLMCallHookContext,
        after_llm_call,
        before_llm_call,
    )
    from policy_engine.adapters.crewai import CrewAIKernel

    step("crewai", "Constructing CrewAIKernel(policy=POLICY) and a per-run context.")
    kernel = CrewAIKernel(policy=POLICY)
    ctx = kernel.create_context("policy-engine-crewai")

    step("crewai", "Registering @before_llm_call: pulls prompt, runs kernel.pre_execute.")

    @before_llm_call
    def gov_before(context: LLMCallHookContext) -> bool | None:
        payload = str(getattr(context, "messages", "") or getattr(context, "prompt", ""))
        allowed, reason = kernel.pre_execute(ctx, payload)
        if not allowed:
            audit("crewai", "before_llm_call", "BLOCKED", reason or "")
            return False
        audit("crewai", "before_llm_call", "ALLOWED")
        return None

    step("crewai", "Registering @after_llm_call: post-LLM audit only.")

    @after_llm_call
    def gov_after(context: LLMCallHookContext) -> str | None:
        audit("crewai", "after_llm_call", "ALLOWED")
        return None

    model = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    step("crewai", f"Resolved LLM model: {model}.")

    step("crewai", "Defining a single-Agent Crew (Greeter).")
    agent = Agent(
        role="Greeter",
        goal="Reply briefly to the user.",
        backstory="You are a concise greeter.",
        llm=model,
        allow_delegation=False,
    )
    task = Task(
        description="Say hello.",
        expected_output="A short greeting.",
        agent=agent,
    )
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential)

    step("crewai", "crew.kickoff_async().")
    result = await crew.kickoff_async()
    step("crewai", "Final crew output:")
    print(result.raw)


if __name__ == "__main__":
    import _shared  # noqa: F401
    asyncio.run(main())
