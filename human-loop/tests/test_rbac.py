import pytest

from human_loop import RBACManager, Role, RolePolicy


def test_rbac_default_roles_assignments_and_custom_permissions():
    manager = RBACManager()

    assert manager.get_role("missing") == Role.READER
    assert manager.has_permission("missing", "read")
    assert not manager.has_permission("missing", "write")

    manager.assign_role("writer", Role.WRITER)
    assert manager.has_permission("writer", "write")
    assert not manager.has_permission("writer", "delete")

    manager.set_permissions(Role.WRITER, {"publish"})
    assert manager.has_permission("writer", "publish")
    assert not manager.has_permission("writer", "write")

    manager.set_policy(Role.WRITER, RolePolicy(max_tool_calls=9, allowed_tools=("publish",), require_human_approval=True))
    assert manager.get_policy("writer").max_tool_calls == 9
    manager.remove_role("writer")
    assert manager.get_role("writer") == Role.READER


def test_rbac_yaml_round_trip(tmp_path):
    pytest.importorskip("yaml")
    manager = RBACManager()
    manager.assign_role("agent-a", Role.ADMIN)
    manager.set_permissions(Role.ADMIN, {"deploy"})
    manager.set_policy(Role.ADMIN, RolePolicy(max_tool_calls=7, allowed_tools=("deploy",)))
    path = tmp_path / "rbac.yaml"

    manager.to_yaml(str(path))
    loaded = RBACManager.from_yaml(str(path))

    assert loaded.get_role("agent-a") == Role.ADMIN
    assert loaded.has_permission("agent-a", "deploy")
    assert loaded.get_policy("agent-a").max_tool_calls == 7
