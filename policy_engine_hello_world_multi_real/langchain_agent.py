"""Real LangChain hello-world agent governed by policy-engine."""

from __future__ import annotations

from _shared import (
    LANGCHAIN_POLICY,
    OPENAI_MODEL,
    PROMPT,
    print_banner,
    require_env,
)


def _last_user_text(state) -> str:
    for msg in reversed(state["messages"]):
        role = getattr(msg, "type", None)
        if role is None and isinstance(msg, tuple):
            role = msg[0]
        if role not in ("human", "user"):
            continue
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, tuple):
            content = msg[1]
        return str(content or "")
    return ""


def main() -> None:
    require_env("OPENAI_API_KEY")
    print_banner("LangChain")

    from langchain_core.messages import SystemMessage
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    from policy_engine.adapters.langchain import LangChainKernel

    kernel = LangChainKernel(policy=LANGCHAIN_POLICY)
    ctx = kernel.create_context("hello-world-langchain")

    def gov_pre_model(state):
        allowed, reason = kernel.pre_execute(ctx, _last_user_text(state))
        if not allowed:
            raise RuntimeError(f"Governance blocked: {reason}")
        return {
            "llm_input_messages": [
                SystemMessage(content="Be friendly and concise."),
                *state["messages"],
            ]
        }

    agent = create_react_agent(
        model=ChatOpenAI(model=OPENAI_MODEL),
        tools=[],
        pre_model_hook=gov_pre_model,
        version="v2",
    )
    result = agent.invoke({"messages": [("user", PROMPT)]})
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
