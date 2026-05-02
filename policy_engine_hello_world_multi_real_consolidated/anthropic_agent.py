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

    client = AnthropicKernel(ANTHROPIC_POLICY).governed_client(anthropic.Anthropic())
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=128,
        messages=[{"role": "user", "content": PROMPT}],
    )
    print(response.content[0].text)


if __name__ == "__main__":
    main()
