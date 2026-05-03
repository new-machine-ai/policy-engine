"""Run consolidated policy-engine examples."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import traceback
from dataclasses import dataclass
from typing import Callable

from _shared import AUDIT, POLICY, audit, reset_steps
from policy_engine import BaseKernel, PolicyRequest


@dataclass(frozen=True)
class Demo:
    key: str
    title: str
    profile: str
    seam: str
    module: str


DEMOS = [
    Demo(
        "langchain",
        "LangChain live hello-world",
        "hello",
        "Seam: LangChainKernel.as_middleware() in create_agent(...).",
        "langchain_agent",
    ),
    Demo(
        "openai_agents",
        "OpenAI Agents SDK live hello-world",
        "hello",
        "Seam: OpenAIAgentsKernel.governed_runner(Runner).",
        "openai_agent",
    ),
    Demo(
        "maf",
        "Microsoft Agent Framework live hello-world",
        "hello",
        "Seam: MAFKernel.as_middleware() in Agent(...).",
        "microsoft_agent",
    ),
    Demo(
        "anthropic",
        "Anthropic SDK live hello-world",
        "hello",
        "Seam: AnthropicKernel.governed_client(...).",
        "anthropic_agent",
    ),
    Demo(
        "claude_hello",
        "Claude Agent SDK live hello-world",
        "hello",
        "Seam: ClaudeSDKKernel.governed_options(...).",
        "claude_agent_sdk_agent",
    ),
    Demo(
        "google_adk",
        "Google ADK live hello-world",
        "hello",
        "Seam: GoogleADKKernel.as_plugin() in InMemoryRunner(plugins=[...]).",
        "google_adk_agent",
    ),
    Demo(
        "governance",
        "Governance showcase — policy, trust, MCP, lifecycle",
        "showcase",
        "Seam: dependency-free orchestration around BaseKernel.evaluate().",
        "governance_showcase",
    ),
    Demo(
        "agent_os",
        "Agent-OS backend — AgentOSKernel",
        "showcase",
        "Seam: BaseKernel-compatible facade backed by Agent-OS PolicyInterceptor.",
        "agent_os_governed",
    ),
    Demo(
        "openai_assist",
        "OpenAI Assistants — OpenAIKernel.wrap",
        "showcase",
        "Seam: kernel.wrap(assistant, client) returns a method-level proxy.",
        "openai_assistants_governed",
    ),
    Demo(
        "crewai",
        "CrewAI — CrewAIKernel + LLM hooks",
        "showcase",
        "Seam: @before_llm_call / @after_llm_call decorators.",
        "crewai_governed",
    ),
    Demo(
        "pydantic_ai",
        "PydanticAI — PydanticAIKernel.wrap",
        "showcase",
        "Seam: kernel.wrap(agent) intercepts run().",
        "pydantic_ai_governed",
    ),
    Demo(
        "claude",
        "Claude Agent SDK — full agent loop",
        "showcase",
        "Seam: shared BaseKernel across UserPromptSubmit, PreToolUse, PostToolUse.",
        "claude_governed",
    ),
    Demo(
        "claude_all_hooks",
        "Claude Agent SDK — every Python-supported hook factory wired",
        "showcase",
        "Seam: all ten hook factories registered in ClaudeAgentOptions.",
        "claude_all_hooks",
    ),
    Demo(
        "policy_deep_dive",
        "Policy engine deep dive — kernel internals walkthrough",
        "showcase",
        "Seam: direct BaseKernel.evaluate() walkthrough; no framework SDK in the loop.",
        "policy_engine_deep_dive",
    ),
    Demo(
        "openai_mcp_security",
        "OpenAI Agents SDK — MCP security scanner/gateway smoke",
        "showcase",
        "Seam: OpenAI Agent configured; MCP tools pre-scanned and gated before runtime use.",
        "openai_mcp_security_agent",
    ),
    Demo(
        "claude_mcp_security",
        "Claude Agent SDK — MCP security scanner/gateway smoke",
        "showcase",
        "Seam: ClaudeAgentOptions configured; MCP tools pre-scanned and gated before runtime use.",
        "claude_mcp_security_agent",
    ),
    Demo(
        "maf_mcp_security",
        "Microsoft Agent Framework — MCP security scanner/gateway smoke",
        "showcase",
        "Seam: MAF Agent middleware configured; MCP tools pre-scanned and gated before runtime use.",
        "maf_mcp_security_agent",
    ),
]


def _print_intro(profile: str) -> None:
    bar = "=" * 72
    print(bar)
    print("  policy-engine — consolidated examples")
    print(bar)
    print(f"  Profile: {profile}")
    print(f"  Shared GovernancePolicy: {POLICY.name}")
    print(f"    blocked_patterns      : {POLICY.blocked_patterns}")
    print(f"    max_tool_calls        : {POLICY.max_tool_calls}")
    print(f"    require_human_approval: {POLICY.require_human_approval}")
    print(f"    blocked_tools         : {POLICY.blocked_tools}")
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


def _print_banner(demo: Demo) -> None:
    bar = "=" * 72
    print(f"\n{bar}\n=== {demo.title}\n=== {demo.seam}\n{bar}")


def _load_main(demo: Demo) -> Callable:
    module = importlib.import_module(demo.module)
    return getattr(module, "main")


async def _run_one(demo: Demo, *, strict: bool) -> bool:
    _print_banner(demo)
    reset_steps(demo.key)
    try:
        fn = _load_main(demo)
        if inspect.iscoroutinefunction(fn):
            await fn()
        else:
            await asyncio.to_thread(fn)
        return True
    except ImportError as exc:
        if strict:
            raise
        print(f"[skip] missing dependency: {exc}")
        return False
    except RuntimeError as exc:
        if strict:
            raise
        print(f"[skip] runtime prerequisite missing: {exc}")
        return False
    except Exception as exc:
        if strict:
            raise
        print(f"[error] {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False


def _print_audit() -> None:
    if not AUDIT:
        return
    bar = "=" * 72
    print(f"\n{bar}\n=== Governance audit trail ({len(AUDIT)} events)\n{bar}")
    print("  Every line below is a policy decision recorded by an adapter.\n")
    for i, event in enumerate(AUDIT, 1):
        detail = f"  {event['detail']}" if event["detail"] else ""
        print(
            f"  [{i:>2}] {event['ts']}  {event['framework']:<18} "
            f"{event['phase']:<22} {event['status']}{detail}"
        )


def _select_demos(profile: str, only: list[str] | None) -> list[Demo]:
    if only:
        wanted = set(only)
        return [demo for demo in DEMOS if demo.key in wanted]
    if profile == "all":
        return list(DEMOS)
    return [demo for demo in DEMOS if demo.profile == profile]


async def async_main() -> int:
    parser = argparse.ArgumentParser(
        description="Run consolidated policy-engine examples."
    )
    parser.add_argument(
        "--profile",
        choices=["hello", "showcase", "all"],
        default="all",
        help="Select a demo profile. Defaults to all.",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=[demo.key for demo in DEMOS],
        help="Run only the listed demos.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail immediately instead of soft-skipping missing dependencies or credentials.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available demos and exit.",
    )
    args = parser.parse_args()

    if args.list:
        for demo in DEMOS:
            print(
                f"  {demo.key:<16} [{demo.profile:<8}] {demo.title}\n"
                f"                   {demo.seam}"
            )
        return 0

    demos = _select_demos(args.profile, args.only)
    _print_intro(args.profile if not args.only else "only")
    if args.profile in ("showcase", "all") and not args.only:
        _run_core_blocked_smoke()

    passed = 0
    for demo in demos:
        if await _run_one(demo, strict=args.strict):
            passed += 1

    _print_audit()
    print(f"\nSummary: {passed} passed, {len(demos) - passed} skipped/failed")
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
