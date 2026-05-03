# Framework: Google ADK (google-adk)
import asyncio

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner

from policy_engine import GovernancePolicy
from policy_engine.adapters.google_adk import GoogleADKKernel


async def main() -> None:
    policy = GovernancePolicy(blocked_patterns=["DROP TABLE"])
    plugin = GoogleADKKernel(policy).as_plugin()

    agent = LlmAgent(
        name="hello",
        model="gemini-2.5-flash",
        instruction="Be friendly.",
    )
    runner = InMemoryRunner(agent=agent, app_name="hello", plugins=[plugin])
    try:
        events = await runner.run_debug("hello", quiet=True)
    finally:
        await runner.close()

    last = next(
        (p.text for ev in reversed(events)
         for p in (getattr(ev.content, "parts", None) or [])
         if getattr(p, "text", None)),
        "",
    )
    print(last)


if __name__ == "__main__":
    asyncio.run(main())
