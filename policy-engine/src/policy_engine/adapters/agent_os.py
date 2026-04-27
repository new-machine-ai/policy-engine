"""Agent-OS adapter — optional richer governance backend.

Seam: ``AgentOSKernel.evaluate(ctx, request)`` keeps the local policy-engine
decision contract while delegating prompt/tool inspection to Agent-OS'
vendor-neutral ``PolicyInterceptor``.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from policy_engine.context import ExecutionContext
from policy_engine.kernel import BaseKernel
from policy_engine.policy import GovernancePolicy, PolicyDecision, PolicyRequest


class AgentOSUnavailableError(ImportError):
    """Raised when the optional Agent-OS backend cannot be loaded."""


_AGENT_OS_BASE: ModuleType | None = None


def _local_agent_os_base_path() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "agent-os" / "src" / "agent_os" / "integrations" / "base.py"
        if candidate.exists():
            return candidate
    return None


def _load_local_agent_os_base(path: Path) -> ModuleType:
    module_name = "_policy_engine_agent_os_integrations_base"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    source = path.read_text(encoding="utf-8")
    # Avoid the trailing compatibility import because it loads agent_os.__init__.
    marker = "\n# Backward compatibility: import from the centralized exception hierarchy"
    if marker in source:
        source = source.split(marker, 1)[0] + "\n"

    module = ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = module_name.rpartition(".")[0]
    sys.modules[module_name] = module
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def _load_agent_os_base() -> ModuleType:
    global _AGENT_OS_BASE
    if _AGENT_OS_BASE is not None:
        return _AGENT_OS_BASE

    local_path = _local_agent_os_base_path()
    if local_path is not None:
        _AGENT_OS_BASE = _load_local_agent_os_base(local_path)
        return _AGENT_OS_BASE

    try:
        _AGENT_OS_BASE = importlib.import_module("agent_os.integrations.base")
        return _AGENT_OS_BASE
    except ImportError as exc:
        raise AgentOSUnavailableError(
            "Agent-OS is not available. Install it with "
            "`pip install -e ./agent-os` from the repo root, or install the "
            "`policy-engine[agent-os]` optional extra."
        ) from exc


def to_agent_os_policy(
    policy: GovernancePolicy,
    *,
    include_tool_allowlist: bool = True,
) -> Any:
    """Convert a local policy into Agent-OS' richer policy type."""
    agent_os_base = _load_agent_os_base()
    agent_os_policy = agent_os_base.GovernancePolicy
    return agent_os_policy(
        name=policy.name,
        max_tool_calls=policy.max_tool_calls,
        allowed_tools=(
            list(policy.allowed_tools or []) if include_tool_allowlist else []
        ),
        blocked_patterns=list(policy.blocked_patterns),
        require_human_approval=policy.require_human_approval,
    )


class AgentOSKernel(BaseKernel):
    """BaseKernel-compatible facade backed by Agent-OS policy interception."""

    framework = "agent_os"

    def __init__(self, policy: GovernancePolicy) -> None:
        super().__init__(policy)
        self._prompt_interceptor: Any | None = None
        self._tool_interceptor: Any | None = None

    def _interceptor(self, *, tool_scoped: bool) -> Any:
        attr = "_tool_interceptor" if tool_scoped else "_prompt_interceptor"
        cached = getattr(self, attr)
        if cached is not None:
            return cached

        agent_os_base = _load_agent_os_base()
        interceptor = agent_os_base.PolicyInterceptor(
            to_agent_os_policy(
                self.policy,
                include_tool_allowlist=tool_scoped,
            )
        )
        setattr(self, attr, interceptor)
        return interceptor

    def evaluate(
        self, ctx: ExecutionContext, request: PolicyRequest | str
    ) -> PolicyDecision:
        if isinstance(request, str):
            request = PolicyRequest(payload=request)

        payload = request.payload or ""
        payload_hash = request.payload_sha256()

        def decision(
            allowed: bool,
            reason: str | None = None,
            *,
            matched_pattern: str | None = None,
            requires_approval: bool = False,
        ) -> PolicyDecision:
            return PolicyDecision(
                allowed=allowed,
                reason=reason,
                policy=self.policy.name,
                matched_pattern=matched_pattern,
                tool_name=request.tool_name,
                requires_approval=requires_approval,
                payload_hash=payload_hash,
                phase=request.phase,
            )

        if ctx.call_count >= self.policy.max_tool_calls:
            return decision(False, "max_tool_calls exceeded")

        if request.tool_name is not None:
            if (
                self.policy.blocked_tools is not None
                and request.tool_name in self.policy.blocked_tools
            ):
                return decision(False, f"blocked_tool:{request.tool_name}")
            if (
                self.policy.allowed_tools is not None
                and request.tool_name not in self.policy.allowed_tools
            ):
                return decision(False, f"tool_not_allowed:{request.tool_name}")

        if self.policy.require_human_approval:
            return decision(
                False,
                "human_approval_required",
                requires_approval=True,
            )

        agent_os_base = _load_agent_os_base()
        tool_request = agent_os_base.ToolCallRequest(
            tool_name=request.tool_name or request.phase or "pre_execute",
            arguments={"payload": payload},
            metadata={
                "policy_engine_phase": request.phase,
                "payload_hash": payload_hash,
            },
        )
        result = self._interceptor(tool_scoped=request.tool_name is not None).intercept(
            tool_request
        )
        if not result.allowed:
            matched = self.policy.matches_pattern(payload)
            if matched is not None:
                return decision(
                    False,
                    f"blocked_pattern:{matched}",
                    matched_pattern=matched,
                )
            return decision(False, f"agent_os:{result.reason or 'blocked'}")

        matched = self.policy.matches_pattern(payload)
        if matched is not None:
            return decision(False, f"blocked_pattern:{matched}", matched_pattern=matched)

        ctx.call_count += 1
        return decision(True)


__all__ = [
    "AgentOSKernel",
    "AgentOSUnavailableError",
    "to_agent_os_policy",
]
