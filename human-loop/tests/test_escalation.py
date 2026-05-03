import threading
import urllib.request

from human_loop import (
    DefaultTimeoutAction,
    EscalationDecision,
    EscalationHandler,
    InMemoryApprovalQueue,
    QuorumConfig,
    WebhookApprovalBackend,
)


def test_escalation_approve_deny_and_timeout_defaults():
    approved_handler = EscalationHandler(timeout_seconds=0)
    approved = approved_handler.escalate("agent-a", "deploy", "risk")
    assert approved_handler.approve(approved.request_id, "alice")
    assert approved_handler.resolve(approved.request_id) == EscalationDecision.ALLOW

    denied_handler = EscalationHandler(timeout_seconds=0)
    denied = denied_handler.escalate("agent-a", "deploy", "risk")
    assert denied_handler.deny(denied.request_id, "bob")
    assert denied_handler.resolve(denied.request_id) == EscalationDecision.DENY

    timeout_deny = EscalationHandler(timeout_seconds=0, default_action=DefaultTimeoutAction.DENY)
    request = timeout_deny.escalate("agent-a", "deploy", "risk")
    assert timeout_deny.resolve(request.request_id) == EscalationDecision.DENY
    assert request.decision == EscalationDecision.TIMEOUT

    timeout_allow = EscalationHandler(timeout_seconds=0, default_action=DefaultTimeoutAction.ALLOW)
    request = timeout_allow.escalate("agent-a", "deploy", "risk")
    assert timeout_allow.resolve(request.request_id) == EscalationDecision.ALLOW
    assert request.decision == EscalationDecision.TIMEOUT


def test_escalation_fatigue_and_audit_privacy():
    handler = EscalationHandler(timeout_seconds=0, fatigue_threshold=1)
    first = handler.escalate("agent-a", "deploy", "first", {"secret": "raw-token"})
    second = handler.escalate("agent-a", "deploy", "second", {"secret": "raw-token"})

    assert first.decision == EscalationDecision.PENDING
    assert second.decision == EscalationDecision.DENY
    assert second.resolved_by == "system:fatigue_detector"
    assert "raw-token" not in str(handler.audit_trail)
    assert handler.audit_trail[-1]["context_hash"]


def test_quorum_approval_and_denial_thresholds():
    approve_handler = EscalationHandler(
        timeout_seconds=0,
        quorum=QuorumConfig(required_approvals=2, total_approvers=3, required_denials=1),
    )
    request = approve_handler.escalate("agent-a", "deploy", "risk")
    assert approve_handler.approve(request.request_id, "alice")
    assert approve_handler.approve(request.request_id, "bob")
    assert approve_handler.resolve(request.request_id) == EscalationDecision.ALLOW

    deny_handler = EscalationHandler(
        timeout_seconds=0,
        quorum=QuorumConfig(required_approvals=2, total_approvers=3, required_denials=1),
    )
    request = deny_handler.escalate("agent-a", "deploy", "risk")
    assert deny_handler.deny(request.request_id, "mallory")
    assert deny_handler.resolve(request.request_id) == EscalationDecision.DENY


def test_in_memory_queue_threaded_votes():
    queue = InMemoryApprovalQueue()
    handler = EscalationHandler(backend=queue, timeout_seconds=1)
    request = handler.escalate("agent-a", "deploy", "risk")

    thread = threading.Thread(target=lambda: handler.approve(request.request_id, "alice"))
    thread.start()
    thread.join()

    assert handler.resolve(request.request_id) == EscalationDecision.ALLOW


def test_webhook_backend_posts_payload(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout):  # noqa: ANN001
        calls.append((req.full_url, req.data, timeout))

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
                return False

        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    backend = WebhookApprovalBackend("https://example.test/hook", headers={"Authorization": "Bearer test"})
    handler = EscalationHandler(backend=backend, timeout_seconds=0)

    request = handler.escalate("agent-a", "deploy", "risk")

    assert request.request_id
    assert len(calls) == 1
    assert calls[0][0] == "https://example.test/hook"
