"""Real Anthropic SDK hello-world request governed by policy-engine."""

from __future__ import annotations

from _shared import (
    ANTHROPIC_MODEL,
    ANTHROPIC_POLICY,
    PROMPT,
    print_banner,
    require_env,
)


def main() -> None:
    require_env("ANTHROPIC_API_KEY")
    print_banner("Anthropic SDK")

    import anthropic

    from policy_engine.adapters.anthropic import AnthropicKernel

    kernel = AnthropicKernel(policy=ANTHROPIC_POLICY)
    hook = kernel.as_message_hook(name="hello-world-anthropic")
    response = hook.create(
        anthropic.Anthropic(),
        model=ANTHROPIC_MODEL,
        max_tokens=128,
        messages=[{"role": "user", "content": PROMPT}],
    )
    print(response.content[0].text)


if __name__ == "__main__":
    main()
