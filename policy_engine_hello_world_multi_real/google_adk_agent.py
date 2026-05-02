"""Live Google ADK hello-world governed by policy-engine."""

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


def _event_text(event: Any) -> str:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    text_parts = [getattr(part, "text", None) for part in parts]
    return "\n".join(part for part in text_parts if part)


def _final_text(events: list[Any]) -> str:
    for event in reversed(events):
        text = _event_text(event)
        if text:
            return text
    return ""


async def main() -> None:
    print_banner("Google ADK")
    require_google_credentials()

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
