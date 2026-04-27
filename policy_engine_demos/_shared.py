"""Shared policy + audit helpers for the policy_engine_demos.

Imports the bare-bones policy_engine package directly from this checkout so
demos run without pip install.
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_CANDIDATES = [
    _HERE.parent / "policy-engine" / "src",                # this checkout
    _HERE.parent.parent / "packages" / "policy-engine" / "src",  # parent monorepo
]
for _src in _CANDIDATES:
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))
        break

from policy_engine import AUDIT, GovernancePolicy, audit  # noqa: E402

POLICY = GovernancePolicy(
    name="lite-policy",
    blocked_patterns=[
        "DROP TABLE",
        "rm -rf",
        "ignore previous instructions",
        "reveal system prompt",
        "<system>",
    ],
    max_tool_calls=10,
    blocked_tools=["shell_exec", "network_request", "file_write"],
)

_STEP_COUNTERS: dict[str, int] = {}


def step(framework: str, message: str) -> None:
    n = _STEP_COUNTERS.get(framework, 0) + 1
    _STEP_COUNTERS[framework] = n
    print(f"  [{framework} step {n}] {message}")


def reset_steps(framework: str) -> None:
    _STEP_COUNTERS[framework] = 0


def _bootstrap_sibling_imports() -> None:
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)


_bootstrap_sibling_imports()

__all__ = ["AUDIT", "POLICY", "audit", "step", "reset_steps"]
