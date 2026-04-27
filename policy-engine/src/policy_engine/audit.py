"""In-memory audit sink with a print helper."""

from datetime import datetime, timezone
from typing import Any

AUDIT: list[dict] = []


def audit(
    framework: str,
    phase: str,
    status: str,
    detail: str = "",
    *,
    decision: Any | None = None,
    policy: str | None = None,
    reason: str | None = None,
    tool_name: str | None = None,
    payload_hash: str | None = None,
) -> None:
    if decision is not None:
        policy = policy or getattr(decision, "policy", None)
        reason = reason if reason is not None else getattr(decision, "reason", None)
        tool_name = tool_name or getattr(decision, "tool_name", None)
        payload_hash = payload_hash or getattr(decision, "payload_hash", None)

    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "framework": framework,
        "phase": phase,
        "status": status,
        "detail": detail,
    }
    if policy:
        record["policy"] = policy
    if reason:
        record["reason"] = reason
    if tool_name:
        record["tool_name"] = tool_name
    if payload_hash:
        record["payload_hash"] = payload_hash

    AUDIT.append(record)
    print(f"gov[{framework}:{phase}] {status}" + (f" - {detail}" if detail else ""))


def reset_audit() -> None:
    AUDIT.clear()
