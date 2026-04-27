"""LangChain (LangGraph) — pre_model_hook delegates to LangChainKernel."""

from _shared import POLICY, audit, step


def main() -> None:
    step("langchain", "Importing LangChain core, langchain-openai, langgraph prebuilt, "
                       "and the policy_engine LangChainKernel.")
    from langchain_core.messages import SystemMessage
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent
    from policy_engine.adapters.langchain import LangChainKernel

    step("langchain", "Constructing LangChainKernel(policy=POLICY) and a per-run context.")
    kernel = LangChainKernel(policy=POLICY)
    ctx = kernel.create_context("policy-engine-langgraph")

    step("langchain", "Defining gov_pre_model — a LangGraph pre_model_hook.")

    def gov_pre_model(state):
        user_text = ""
        for msg in reversed(state["messages"]):
            role = getattr(msg, "type", None) or (
                msg[0] if isinstance(msg, tuple) else None
            )
            if role in ("human", "user"):
                user_text = getattr(msg, "content", None) or (
                    msg[1] if isinstance(msg, tuple) else ""
                )
                break
        allowed, reason = kernel.pre_execute(ctx, user_text)
        if not allowed:
            audit("langchain", "pre_model_hook", "BLOCKED", reason or "")
            raise RuntimeError(f"Governance blocked: {reason}")
        audit("langchain", "pre_model_hook", "ALLOWED")
        return {
            "llm_input_messages": [
                SystemMessage("Reply briefly."),
                *state["messages"],
            ]
        }

    step("langchain", "Building a ReAct agent with pre_model_hook=gov_pre_model.")
    agent = create_react_agent(
        model=ChatOpenAI(model="gpt-4o-mini"),
        tools=[],
        pre_model_hook=gov_pre_model,
        version="v2",
    )

    step("langchain", "Invoking agent with 'Say hello.'.")
    result = agent.invoke({"messages": [("user", "Say hello.")]})
    audit("langchain", "post_invoke", "ALLOWED")
    step("langchain", "Final agent output:")
    print(result["messages"][-1].content)


if __name__ == "__main__":
    import _shared  # noqa: F401
    main()
