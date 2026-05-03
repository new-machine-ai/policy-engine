"""Real Google ADK hello-world agent governed by policy-engine."""

from __future__ import annotations

import asyncio
from typing import Any

from _shared import (
    GOOGLE_ADK_MODEL,
    GOOGLE_ADK_POLICY,
    PROMPT,
    print_banner,
    require_google_credentials,
)


def _final_text(events: list[Any]) -> str:
    for event in reversed(events):
        parts = getattr(getattr(event, "content", None), "parts", None) or []
        text = "\n".join(p for p in (getattr(part, "text", None) for part in parts) if p)
        if text:
            return text
    return ""


async def main() -> None:
    require_google_credentials()
    print_banner("Google ADK")

    from google.adk.agents import LlmAgent
    from google.adk.runners import InMemoryRunner

    from policy_engine.adapters.google_adk import GoogleADKKernel

    kernel = GoogleADKKernel(GOOGLE_ADK_POLICY)
    agent = LlmAgent(
        name="policy_engine_google_adk_hello",
        model=GOOGLE_ADK_MODEL,
        instruction="Be friendly and concise.",
    )
    runner = InMemoryRunner(
        agent=agent,
        app_name="policy-engine-google-adk",
        plugins=[kernel.as_plugin()],
    )
    try:
        events = await runner.run_debug(PROMPT, quiet=True)
    finally:
        await runner.close()

    print(_final_text(events) or "(no text response)")
    stats = kernel.get_stats()
    print(
        f"policy={GOOGLE_ADK_POLICY.name} "
        f"audit_events={stats['audit_events']} "
        f"violations={stats['violations']}"
    )


if __name__ == "__main__":
    asyncio.run(main())
