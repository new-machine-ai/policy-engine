"""Real LangChain hello-world agent governed by policy-engine."""

from __future__ import annotations

from _shared import LANGCHAIN_POLICY, OPENAI_MODEL, PROMPT, print_banner, require_env


def main() -> None:
    require_env("OPENAI_API_KEY")
    print_banner("LangChain")

    from langchain.agents import create_agent

    from policy_engine.adapters.langchain import LangChainKernel

    kernel = LangChainKernel(policy=LANGCHAIN_POLICY)
    agent = create_agent(
        model=OPENAI_MODEL,
        tools=[],
        system_prompt="Be friendly and concise.",
        middleware=[kernel.as_middleware()],
    )
    result = agent.invoke({"messages": [{"role": "user", "content": PROMPT}]})
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
