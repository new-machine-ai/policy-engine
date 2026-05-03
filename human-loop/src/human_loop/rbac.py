# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Local role-based access control for agent actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    """Standard access-control roles."""

    READER = "reader"
    WRITER = "writer"
    ADMIN = "admin"
    AUDITOR = "auditor"


@dataclass(frozen=True)
class RolePolicy:
    """Local policy template attached to a role."""

    max_tool_calls: int = 0
    allowed_tools: tuple[str, ...] = ()
    require_human_approval: bool = True
    log_all_calls: bool = False
    max_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_tool_calls": self.max_tool_calls,
            "allowed_tools": list(self.allowed_tools),
            "require_human_approval": self.require_human_approval,
            "log_all_calls": self.log_all_calls,
            "max_tokens": self.max_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RolePolicy":
        return cls(
            max_tool_calls=int(data.get("max_tool_calls", 0)),
            allowed_tools=tuple(data.get("allowed_tools", ())),
            require_human_approval=bool(data.get("require_human_approval", True)),
            log_all_calls=bool(data.get("log_all_calls", False)),
            max_tokens=data.get("max_tokens"),
        )


DEFAULT_ROLE = Role.READER
_ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.READER: {"read"},
    Role.WRITER: {"read", "write", "search"},
    Role.ADMIN: {"read", "write", "search", "admin", "delete", "audit", "deploy", "execute_trade", "execute_code"},
    Role.AUDITOR: {"read", "search", "audit"},
}
_DEFAULT_POLICIES: dict[Role, RolePolicy] = {
    Role.READER: RolePolicy(max_tool_calls=0, allowed_tools=(), require_human_approval=True),
    Role.WRITER: RolePolicy(max_tool_calls=5, allowed_tools=("read", "write", "search"), require_human_approval=False),
    Role.ADMIN: RolePolicy(max_tool_calls=50, allowed_tools=(), max_tokens=16384, require_human_approval=False),
    Role.AUDITOR: RolePolicy(max_tool_calls=5, allowed_tools=("read", "search", "audit"), log_all_calls=True, require_human_approval=False),
}


class RBACManager:
    """Assign roles and check action permissions for agents."""

    def __init__(self) -> None:
        self._roles: dict[str, Role] = {}
        self._custom_policies: dict[Role, RolePolicy] = {}
        self._custom_permissions: dict[Role, set[str]] = {}

    def assign_role(self, agent_id: str, role: Role | str) -> None:
        self._roles[agent_id] = Role(role)

    def get_role(self, agent_id: str) -> Role:
        return self._roles.get(agent_id, DEFAULT_ROLE)

    def get_policy(self, agent_id: str) -> RolePolicy:
        role = self.get_role(agent_id)
        return self._custom_policies.get(role, _DEFAULT_POLICIES[role])

    def has_permission(self, agent_id: str, action: str) -> bool:
        role = self.get_role(agent_id)
        permissions = self._custom_permissions.get(role, _ROLE_PERMISSIONS.get(role, set()))
        return action in permissions

    def remove_role(self, agent_id: str) -> None:
        self._roles.pop(agent_id, None)

    def set_permissions(self, role: Role | str, permissions: set[str] | list[str] | tuple[str, ...]) -> None:
        self._custom_permissions[Role(role)] = set(permissions)

    def set_policy(self, role: Role | str, policy: RolePolicy) -> None:
        self._custom_policies[Role(role)] = policy

    def to_yaml(self, path: str) -> None:
        try:
            import yaml
        except ImportError as exc:
            raise ImportError("Install human-loop[yaml] to use YAML RBAC serialization.") from exc
        data: dict[str, Any] = {
            "assignments": {agent: role.value for agent, role in self._roles.items()},
            "custom_permissions": {
                role.value: sorted(permissions)
                for role, permissions in self._custom_permissions.items()
            },
            "custom_policies": {
                role.value: policy.to_dict()
                for role, policy in self._custom_policies.items()
            },
        }
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, sort_keys=False)

    @classmethod
    def from_yaml(cls, path: str) -> "RBACManager":
        try:
            import yaml
        except ImportError as exc:
            raise ImportError("Install human-loop[yaml] to use YAML RBAC serialization.") from exc
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        if not isinstance(data, dict):
            raise ValueError("RBAC YAML must contain a mapping")
        manager = cls()
        for agent_id, role_value in (data.get("assignments") or {}).items():
            manager.assign_role(str(agent_id), Role(role_value))
        for role_value, permissions in (data.get("custom_permissions") or {}).items():
            manager.set_permissions(Role(role_value), set(permissions))
        for role_value, policy_data in (data.get("custom_policies") or {}).items():
            manager.set_policy(Role(role_value), RolePolicy.from_dict(policy_data))
        return manager
