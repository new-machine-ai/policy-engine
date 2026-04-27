#!/usr/bin/env python3
"""Orchestrator for the policy_engine_demos.

Runs each adapter quickstart, prints a banner with the seam, and finishes
with a unified governance audit trail.

Usage:
    python examples/policy_engine_demos/run_all.py
    python examples/policy_engine_demos/run_all.py --only langchain crewai
    python examples/policy_engine_demos/run_all.py --list
"""

import argparse
import asyncio
import inspect
import traceback

from _shared import AUDIT, POLICY, audit, reset_steps
from policy_engine import BaseKernel, PolicyRequest


def _load_demos():
    from governance_showcase import main as governance_main
    from agent_os_governed import main as agent_os_main
    from maf_governed import main as maf_main
    from openai_assistants_governed import main as oai_assistants_main
    from openai_agents_sdk_governed import main as oai_agents_main
    from langchain_governed import main as langchain_main
    from crewai_governed import main as crewai_main
    from pydantic_ai_governed import main as pydantic_main
    from claude_governed import main as claude_main

    return [
        (
            "governance",
            "Governance showcase — policy, trust, MCP, lifecycle",
            "Seam: dependency-free orchestration around BaseKernel.evaluate().",
            governance_main,
        ),
        (
            "agent_os",
            "Agent-OS backend — AgentOSKernel",
            "Seam: BaseKernel-compatible facade backed by Agent-OS PolicyInterceptor.",
            agent_os_main,
        ),
        (
            "maf",
            "MAF — create_governance_middleware",
            "Seam: Agent(middleware=[...]) — list returned by adapter factory.",
            maf_main,
        ),
        (
            "openai_assist",
            "OpenAI Assistants — OpenAIKernel.wrap",
            "Seam: kernel.wrap(assistant, client) returns a method-level proxy.",
            oai_assistants_main,
        ),
        (
            "openai_agents",
            "OpenAI Agents SDK — OpenAIAgentsKernel",
            "Seam: RunHooks lifecycle + wrapped Agent + wrapped Runner.",
            oai_agents_main,
        ),
        (
            "langchain",
            "LangChain (LangGraph) — LangChainKernel",
            "Seam: create_react_agent(pre_model_hook=...) — runs before every LLM call.",
            langchain_main,
        ),
        (
            "crewai",
            "CrewAI — CrewAIKernel + LLM hooks",
            "Seam: @before_llm_call / @after_llm_call decorators.",
            crewai_main,
        ),
        (
            "pydantic_ai",
            "PydanticAI — PydanticAIKernel.wrap",
            "Seam: kernel.wrap(agent) intercepts run().",
            pydantic_main,
        ),
        (
            "claude",
            "Claude Agent SDK — make_user_prompt_hook",
            "Seam: HookMatcher with a closure over POLICY.",
            claude_main,
        ),
    ]


def _print_intro() -> None:
    bar = "=" * 72
    print(bar)
    print("  policy-engine — bare-bones runtime policy demos")
    print(bar)
    print(f"  Shared GovernancePolicy: {POLICY.name}")
    print(f"    blocked_patterns      : {POLICY.blocked_patterns}")
    print(f"    max_tool_calls        : {POLICY.max_tool_calls}")
    print(f"    require_human_approval: {POLICY.require_human_approval}")
    print(f"    blocked_tools         : {POLICY.blocked_tools}")
    print()
    print("  Same policy enforced across 7 frameworks via thin adapters,")
    print("  plus a dependency-free governance showcase and optional Agent-OS backend.")
    print("  Core imports stay lightweight; Agent-OS is loaded only by its adapter demo.")
    print(bar)


def _run_core_blocked_smoke() -> None:
    kernel = BaseKernel(POLICY)
    ctx = kernel.create_context("demo-core-smoke")
    decision = kernel.evaluate(
        ctx,
        PolicyRequest(payload="Please DROP TABLE users", phase="demo_preflight"),
    )
    status = "ALLOWED" if decision.allowed else "BLOCKED"
    detail = decision.reason or ""
    print(f"  Core blocked-path smoke: {status}" + (f" ({detail})" if detail else ""))
    audit("core", "demo_preflight", status, detail, decision=decision)


def _print_banner(title: str, seam: str) -> None:
    bar = "=" * 72
    print(f"\n{bar}\n=== {title}\n=== {seam}\n{bar}")


async def _run_one(key: str, title: str, seam: str, fn) -> None:
    _print_banner(title, seam)
    reset_steps(key)
    try:
        if inspect.iscoroutinefunction(fn):
            await fn()
        else:
            await asyncio.to_thread(fn)
    except ImportError as e:
        print(f"[skip] missing dependency: {e}")
    except Exception as e:
        print(f"[error] {type(e).__name__}: {e}")
        traceback.print_exc()


def _print_audit() -> None:
    if not AUDIT:
        return
    bar = "=" * 72
    print(f"\n{bar}\n=== Governance audit trail ({len(AUDIT)} events)\n{bar}")
    print("  Every line below is a policy decision recorded by an adapter.\n")
    for i, e in enumerate(AUDIT, 1):
        detail = f"  {e['detail']}" if e["detail"] else ""
        print(
            f"  [{i:>2}] {e['ts']}  {e['framework']:<18} "
            f"{e['phase']:<22} {e['status']}{detail}"
        )


async def main() -> None:
    demos = _load_demos()
    parser = argparse.ArgumentParser(description="Run the policy_engine_demos.")
    parser.add_argument(
        "--only",
        nargs="+",
        choices=[k for k, *_ in demos],
        help="Run only the listed demos.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available demos and exit.",
    )
    args = parser.parse_args()

    if args.list:
        for key, title, seam, _ in demos:
            print(f"  {key:<14} {title}\n                 {seam}")
        return

    selected = set(args.only) if args.only else None
    _print_intro()
    _run_core_blocked_smoke()
    for key, title, seam, fn in demos:
        if selected and key not in selected:
            continue
        await _run_one(key, title, seam, fn)
    _print_audit()


if __name__ == "__main__":
    asyncio.run(main())
