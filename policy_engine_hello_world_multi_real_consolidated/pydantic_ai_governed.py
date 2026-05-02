"""PydanticAI — PydanticAIKernel.wrap from policy_engine."""

import asyncio
import os

from _shared import POLICY, audit, step


async def main() -> None:
    step("pydantic_ai", "Importing PydanticAI Agent and the policy_engine adapter.")
    from pydantic_ai import Agent
    from policy_engine.adapters.pydantic_ai import (
        PydanticAIKernel,
        PolicyViolationError,
    )

    if not os.environ.get("OPENAI_API_KEY"):
        print("[skip] set OPENAI_API_KEY to run this demo")
        return

    model = os.environ.get("OPENAI_MODEL") or "openai:gpt-4o-mini"
    if ":" not in model:
        model = f"openai:{model}"
    step("pydantic_ai", f"Resolved model identifier: {model}.")

    step("pydantic_ai", "Constructing the raw PydanticAI Agent.")
    raw_agent = Agent(model, system_prompt="Reply briefly.")

    step("pydantic_ai", "Constructing PydanticAIKernel(policy=POLICY) and wrapping the agent.")
    kernel = PydanticAIKernel(policy=POLICY)
    governed = kernel.wrap(raw_agent)
    audit("pydantic_ai", "wrap", "ALLOWED")

    try:
        step("pydantic_ai", "Calling governed.run('Say hello.').")
        result = await governed.run("Say hello.")
        output = getattr(result, "output", None) or getattr(result, "data", result)
        audit("pydantic_ai", "run", "ALLOWED", f"{len(str(output))}ch")
        step("pydantic_ai", "Final agent output:")
        print(output)
    except PolicyViolationError as e:
        audit("pydantic_ai", "run", "BLOCKED", str(e))


if __name__ == "__main__":
    import _shared  # noqa: F401
    asyncio.run(main())
