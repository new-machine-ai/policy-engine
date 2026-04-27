"""OpenAI Assistants — OpenAIKernel.wrap from policy_engine."""

import asyncio
import os

from _shared import POLICY, audit, step


async def main() -> None:
    step("openai_assistants", "Importing the OpenAI SDK and the policy_engine adapter.")
    from openai import OpenAI
    from policy_engine.adapters.openai_assistants import (
        OpenAIKernel,
        PolicyViolationError,
    )

    if not os.environ.get("OPENAI_API_KEY"):
        print("[skip] set OPENAI_API_KEY to run this demo")
        return

    step("openai_assistants", "Constructing OpenAI client + OpenAIKernel(policy=POLICY).")
    client = OpenAI()
    kernel = OpenAIKernel(policy=POLICY)

    step("openai_assistants", "Creating an Assistant via the un-governed client.")
    assistant = client.beta.assistants.create(
        name="policy-engine-assistant",
        instructions="Reply briefly.",
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    )
    audit("openai_assistants", "assistant_created", "ALLOWED", assistant.id)
    step("openai_assistants", f"Assistant created: id={assistant.id}.")

    try:
        step("openai_assistants", "kernel.wrap(assistant, client) → method-level proxy.")
        governed = kernel.wrap(assistant, client)

        step("openai_assistants", "governed.create_thread()")
        thread = governed.create_thread()
        audit("openai_assistants", "thread_created", "ALLOWED", thread.id)

        try:
            step("openai_assistants", "governed.add_message(...) — prompt checked first.")
            governed.add_message(thread.id, "Say hello.")
            audit("openai_assistants", "add_message", "ALLOWED")

            step("openai_assistants", "governed.run(thread.id) — polls run to completion.")
            run = governed.run(thread.id)
            audit("openai_assistants", "run", "ALLOWED", run.status)

            step("openai_assistants", "Listing newest message and printing the reply.")
            messages = governed.list_messages(thread.id, order="desc", limit=1)
            for m in messages.data[:1]:
                for part in m.content:
                    if getattr(part, "type", None) == "text":
                        print(part.text.value)
        except PolicyViolationError as e:
            audit("openai_assistants", "run", "BLOCKED", str(e))
        finally:
            step("openai_assistants", "Deleting the thread.")
            governed.delete_thread(thread.id)
    finally:
        step("openai_assistants", "Deleting the Assistant.")
        client.beta.assistants.delete(assistant.id)
        audit("openai_assistants", "assistant_deleted", "ALLOWED", assistant.id)


if __name__ == "__main__":
    import _shared  # noqa: F401
    asyncio.run(main())
