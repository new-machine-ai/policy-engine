from human_loop import (
    ActionDescriptor,
    ReversibilityChecker,
    ReversibilityLevel,
    ReversibilityRegistry,
)


def test_reversibility_classification_compensation_and_blocking():
    checker = ReversibilityChecker(block_irreversible=True)

    assert checker.assess("write_file").level == ReversibilityLevel.FULLY_REVERSIBLE
    assert checker.assess("send_email").level == ReversibilityLevel.PARTIALLY_REVERSIBLE
    assert checker.assess("deploy").level == ReversibilityLevel.IRREVERSIBLE
    assert checker.assess("unknown_action").level == ReversibilityLevel.UNKNOWN
    assert checker.get_compensation_plan("deploy")[0].action == "rollback_deploy"
    assert checker.should_block("deploy")
    assert checker.is_safe("write_file")


def test_reversibility_registry_registration_lookup_and_unhealthy_undo():
    registry = ReversibilityRegistry("session-1")
    action = ActionDescriptor(
        action_id="deploy-prod",
        execute_api="deploy",
        undo_api="rollback",
        reversibility=ReversibilityLevel.IRREVERSIBLE,
        undo_window_seconds=300,
        compensation_method="rollback_deploy",
        risk_weight=0.9,
    )

    entry = registry.register(action)

    assert entry.risk_weight == 0.9
    assert registry.get("deploy-prod") is entry
    assert registry.get_undo_api("deploy-prod") == "rollback"
    assert not registry.is_reversible("deploy-prod")
    assert registry.has_non_reversible_actions()
    assert registry.non_reversible_actions == ["deploy-prod"]

    registry.mark_undo_unhealthy("deploy-prod")
    assert not entry.undo_api_healthy
    assert entry.last_health_check

    count = registry.register_from_manifest(
        [
            ActionDescriptor("write-file", "write_file", "restore", ReversibilityLevel.FULLY_REVERSIBLE),
        ]
    )
    assert count == 1
    assert registry.is_reversible("write-file")
