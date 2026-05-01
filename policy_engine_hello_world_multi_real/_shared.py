"""Shared helpers for the live hello-world policy-engine demos."""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

for src in (
    REPO_ROOT / "policy-engine" / "src",
    REPO_ROOT.parent / "packages" / "policy-engine" / "src",
):
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
        break

from policy_engine import GovernancePolicy  # noqa: E402

PROMPT = "Say hello in 5 words"

OPENAI_MODEL = (
    os.environ.get("OPENAI_MODEL")
    or os.environ.get("OPENAI_CHAT_MODEL")
    or "gpt-4o-mini"
)
ANTHROPIC_MODEL = os.environ.get(
    "ANTHROPIC_MODEL",
    "claude-sonnet-4-5-20250929",
)

LANGCHAIN_POLICY = GovernancePolicy(
    name="hello-langchain",
    blocked_patterns=["password"],
    max_tool_calls=5,
)
OPENAI_AGENTS_POLICY = GovernancePolicy(
    name="hello-openai-agents",
    blocked_patterns=["password", "DROP TABLE"],
    max_tool_calls=5,
)
MAF_POLICY = GovernancePolicy(
    name="hello-maf",
    blocked_patterns=["password"],
    blocked_tools=["shell_exec"],
    max_tool_calls=5,
)
ANTHROPIC_POLICY = GovernancePolicy(
    name="hello-anthropic",
    blocked_patterns=["password", "api_key"],
    max_tool_calls=5,
)
CLAUDE_AGENT_SDK_POLICY = GovernancePolicy(
    name="hello-claude-agent-sdk",
    blocked_patterns=["password", "api_key"],
    allowed_tools=[],
    max_tool_calls=5,
)


def require_env(name: str) -> None:
    if not os.environ.get(name):
        raise RuntimeError(f"{name} is required for this live demo")


def print_banner(name: str) -> None:
    print(f"\n=== {name} ===")


async def claude_prompt_stream(text: str, *, session_id: str = "hello"):
    """Async iterable for the Claude Agent SDK ``query(prompt=...)`` argument."""
    yield {
        "type": "user",
        "message": {"role": "user", "content": text},
        "parent_tool_use_id": None,
        "session_id": session_id,
    }


__all__ = [
    "ANTHROPIC_MODEL",
    "ANTHROPIC_POLICY",
    "CLAUDE_AGENT_SDK_POLICY",
    "HERE",
    "LANGCHAIN_POLICY",
    "MAF_POLICY",
    "OPENAI_AGENTS_POLICY",
    "OPENAI_MODEL",
    "PROMPT",
    "claude_prompt_stream",
    "print_banner",
    "require_env",
]
