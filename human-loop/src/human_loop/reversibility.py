# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Action reversibility assessment and registry primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ReversibilityLevel(str, Enum):
    """How reversible an action is."""

    FULLY_REVERSIBLE = "fully_reversible"
    PARTIALLY_REVERSIBLE = "partially_reversible"
    IRREVERSIBLE = "irreversible"
    UNKNOWN = "unknown"
    NONE = "none"

    @property
    def default_risk_weight(self) -> float:
        return {
            ReversibilityLevel.FULLY_REVERSIBLE: 0.1,
            ReversibilityLevel.PARTIALLY_REVERSIBLE: 0.5,
            ReversibilityLevel.IRREVERSIBLE: 1.0,
            ReversibilityLevel.UNKNOWN: 0.9,
            ReversibilityLevel.NONE: 1.0,
        }[self]


@dataclass(frozen=True)
class CompensatingAction:
    """An action that can undo or mitigate a previous action."""

    description: str
    action: str
    parameters: dict[str, Any] = field(default_factory=dict)
    effectiveness: str = "full"
    time_window: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "action": self.action,
            "parameters": dict(self.parameters),
            "effectiveness": self.effectiveness,
            "time_window": self.time_window,
        }


@dataclass(frozen=True)
class ReversibilityAssessment:
    """Pre-execution assessment of action reversibility."""

    action: str
    level: ReversibilityLevel
    reason: str
    compensating_actions: tuple[CompensatingAction, ...] = ()
    requires_extra_approval: bool = False
    assessed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "level": self.level.value,
            "reason": self.reason,
            "compensating_actions": [action.to_dict() for action in self.compensating_actions],
            "requires_extra_approval": self.requires_extra_approval,
            "assessed_at": self.assessed_at.isoformat(),
        }


class ReversibilityChecker:
    """Assess action reversibility before execution."""

    def __init__(
        self,
        custom_rules: dict[str, dict[str, Any]] | None = None,
        block_irreversible: bool = False,
    ) -> None:
        self._rules = dict(_REVERSIBILITY_MAP)
        if custom_rules:
            self._rules.update(custom_rules)
        self._block_irreversible = block_irreversible

    def assess(self, action: str) -> ReversibilityAssessment:
        rule = self._rules.get(action)
        if not rule:
            return ReversibilityAssessment(
                action=action,
                level=ReversibilityLevel.UNKNOWN,
                reason=f"No reversibility data for action '{action}'",
                requires_extra_approval=True,
            )
        return ReversibilityAssessment(
            action=action,
            level=ReversibilityLevel(rule["level"]),
            reason=str(rule["reason"]),
            compensating_actions=tuple(rule.get("compensating", ())),
            requires_extra_approval=bool(rule.get("requires_extra_approval", False)),
        )

    def is_safe(self, action: str) -> bool:
        return self.assess(action).level == ReversibilityLevel.FULLY_REVERSIBLE

    def should_block(self, action: str) -> bool:
        return self._block_irreversible and self.assess(action).level == ReversibilityLevel.IRREVERSIBLE

    def get_compensation_plan(self, action: str) -> list[CompensatingAction]:
        return list(self.assess(action).compensating_actions)


@dataclass(frozen=True)
class ActionDescriptor:
    """Local action descriptor for registry registration."""

    action_id: str
    execute_api: str
    undo_api: str | None
    reversibility: ReversibilityLevel
    undo_window_seconds: int = 0
    compensation_method: str | None = None
    risk_weight: float | None = None


@dataclass
class ReversibilityEntry:
    """An action entry in the reversibility registry."""

    action_id: str
    execute_api: str
    undo_api: str | None
    reversibility: ReversibilityLevel
    undo_window_seconds: int
    compensation_method: str | None
    risk_weight: float
    undo_api_healthy: bool = True
    last_health_check: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "execute_api": self.execute_api,
            "undo_api": self.undo_api,
            "reversibility": self.reversibility.value,
            "undo_window_seconds": self.undo_window_seconds,
            "compensation_method": self.compensation_method,
            "risk_weight": self.risk_weight,
            "undo_api_healthy": self.undo_api_healthy,
            "last_health_check": self.last_health_check,
        }


class ReversibilityRegistry:
    """Session-scoped action reversibility registry."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._entries: dict[str, ReversibilityEntry] = {}

    def register(self, action: ActionDescriptor) -> ReversibilityEntry:
        level = ReversibilityLevel(action.reversibility)
        entry = ReversibilityEntry(
            action_id=action.action_id,
            execute_api=action.execute_api,
            undo_api=action.undo_api,
            reversibility=level,
            undo_window_seconds=action.undo_window_seconds,
            compensation_method=action.compensation_method,
            risk_weight=action.risk_weight if action.risk_weight is not None else level.default_risk_weight,
        )
        self._entries[action.action_id] = entry
        return entry

    def register_from_manifest(self, actions: list[ActionDescriptor]) -> int:
        for action in actions:
            self.register(action)
        return len(actions)

    def get(self, action_id: str) -> ReversibilityEntry | None:
        return self._entries.get(action_id)

    def get_undo_api(self, action_id: str) -> str | None:
        entry = self._entries.get(action_id)
        return entry.undo_api if entry else None

    def is_reversible(self, action_id: str) -> bool:
        entry = self._entries.get(action_id)
        if entry is None:
            return False
        return entry.reversibility in {
            ReversibilityLevel.FULLY_REVERSIBLE,
            ReversibilityLevel.PARTIALLY_REVERSIBLE,
        }

    def get_risk_weight(self, action_id: str) -> float:
        entry = self._entries.get(action_id)
        return entry.risk_weight if entry else ReversibilityLevel.NONE.default_risk_weight

    def has_non_reversible_actions(self) -> bool:
        return bool(self.non_reversible_actions)

    def mark_undo_unhealthy(self, action_id: str) -> None:
        entry = self._entries.get(action_id)
        if entry:
            entry.undo_api_healthy = False
            entry.last_health_check = datetime.now(UTC).isoformat()

    @property
    def entries(self) -> list[ReversibilityEntry]:
        return list(self._entries.values())

    @property
    def non_reversible_actions(self) -> list[str]:
        return [
            entry.action_id
            for entry in self._entries.values()
            if entry.reversibility in {ReversibilityLevel.IRREVERSIBLE, ReversibilityLevel.NONE}
        ]


_REVERSIBILITY_MAP: dict[str, dict[str, Any]] = {
    "write_file": {
        "level": ReversibilityLevel.FULLY_REVERSIBLE,
        "reason": "File writes can be reverted by restoring a previous version",
        "compensating": (
            CompensatingAction("Restore previous file version", "restore_file_backup"),
        ),
    },
    "create_file": {
        "level": ReversibilityLevel.FULLY_REVERSIBLE,
        "reason": "Created files can be deleted",
        "compensating": (
            CompensatingAction("Delete the created file", "delete_file"),
        ),
    },
    "database_write": {
        "level": ReversibilityLevel.FULLY_REVERSIBLE,
        "reason": "Database writes can be rolled back within transaction scope",
        "compensating": (
            CompensatingAction("Rollback transaction", "rollback_transaction", time_window="within transaction scope"),
        ),
    },
    "create_pr": {
        "level": ReversibilityLevel.FULLY_REVERSIBLE,
        "reason": "Pull requests can be closed",
        "compensating": (
            CompensatingAction("Close the pull request", "close_pr"),
        ),
    },
    "send_email": {
        "level": ReversibilityLevel.PARTIALLY_REVERSIBLE,
        "reason": "Email recall may work internally, but external delivery cannot be undone",
        "compensating": (
            CompensatingAction("Recall email internally", "recall_email", effectiveness="partial", time_window="30 minutes"),
            CompensatingAction("Send correction or retraction", "send_correction", effectiveness="mitigation-only"),
        ),
    },
    "update_record": {
        "level": ReversibilityLevel.PARTIALLY_REVERSIBLE,
        "reason": "Previous value may be recoverable from audit trail",
        "compensating": (
            CompensatingAction("Restore from audit trail", "restore_from_audit", effectiveness="partial"),
        ),
    },
    "deploy": {
        "level": ReversibilityLevel.IRREVERSIBLE,
        "reason": "Production deployments affect live users immediately",
        "compensating": (
            CompensatingAction("Rollback deployment", "rollback_deploy", effectiveness="partial"),
        ),
        "requires_extra_approval": True,
    },
    "delete_file": {
        "level": ReversibilityLevel.IRREVERSIBLE,
        "reason": "Deleted files may not be recoverable without backups",
        "compensating": (
            CompensatingAction("Restore from backup if available", "restore_from_backup", effectiveness="partial"),
        ),
        "requires_extra_approval": True,
    },
    "delete_record": {
        "level": ReversibilityLevel.IRREVERSIBLE,
        "reason": "Deleted records may not be recoverable",
        "compensating": (),
        "requires_extra_approval": True,
    },
    "execute_trade": {
        "level": ReversibilityLevel.IRREVERSIBLE,
        "reason": "Executed trades are settled and cannot be undone",
        "compensating": (
            CompensatingAction("Execute offsetting trade", "offsetting_trade", effectiveness="mitigation-only"),
        ),
        "requires_extra_approval": True,
    },
    "ssh_connect": {
        "level": ReversibilityLevel.IRREVERSIBLE,
        "reason": "Remote commands may have irreversible effects",
        "compensating": (),
        "requires_extra_approval": True,
    },
    "execute_code": {
        "level": ReversibilityLevel.IRREVERSIBLE,
        "reason": "Arbitrary code execution effects are unpredictable",
        "compensating": (),
        "requires_extra_approval": True,
    },
}
