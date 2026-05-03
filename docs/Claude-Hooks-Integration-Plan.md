# Plan: Wire the missing Claude SDK hooks to `agent-os` and `agent-compliance`

## Context

The current `policy_engine.adapters.claude` module covers 3 of the 10 Python-supported Claude Agent SDK hook events (`UserPromptSubmit`, `PreToolUse`, `PostToolUse`). Seven events are unused: `Stop`, `SubagentStart`, `SubagentStop`, `PreCompact`, `PostToolUseFailure`, `PermissionRequest`, `Notification`.

Two governance backends sit alongside the policy engine in this checkout:

- **`agent-os/`** — event-driven runtime with a rich extension surface: `GovernanceEventBus` (pub/sub), `GovernanceAuditLogger` with pluggable backends, `EscalationManager` (async approval), `WebhookNotifier`, `ConversationGuardian` for transcripts, and a typed exception hierarchy with `error_code` discriminators. The existing `policy_engine.adapters.agent_os.AgentOSKernel` already lazy-loads `agent_os.integrations.base.PolicyInterceptor` for the `pre_execute` gate; nothing yet bridges to the broader event/escalation/notification surface.
- **`agent-compliance/`** — passive validators and producers (`PromptDefenseEvaluator.to_audit_entry`, `PromotionChecker`, `validate_attestation`, `SecurityFinding`, `GovernanceAttestation`). Not event-driven; designed to be *called* by an event-driven layer like agent-os and have its dataclass results piped into `agentmesh.governance.audit.AuditChain.add_entry()`.

This plan wires the seven missing Claude hooks into both backends so a Claude session emits a complete governance trail: lifecycle to agent-os, validation to agent-compliance, both threaded through the existing `policy_engine.audit.AUDIT` log so `run_all.py`'s unified summary stays canonical.

**Outcome:** a Claude SDK session running through the policy engine produces (a) a Claude-side audit row per event, (b) an agent-os event-bus publication and (where applicable) audit-logger record, and (c) for compaction and stop events, an agent-compliance dataclass that downstream tooling can validate.

## What `agent-os` and `agent-compliance` actually expose

| Capability | `agent-os` symbol | `agent-compliance` symbol | Available now? |
|---|---|---|---|
| Pub/sub bus | `GovernanceEventBus.publish` / `.subscribe` | — | ✅ agent-os |
| Write-only audit sink | `GovernanceAuditLogger.log_decision` (+ `JsonlFileBackend`, `InMemoryBackend`) | `to_audit_entry(...)` → dict for `AuditChain.add_entry()` | ✅ both |
| Async human approval | `await EscalationManager.request_approval(...)` returns `EscalationDecision` | `validate_attestation(pr_body, required_sections)` (sync, no callback) | ✅ both, different shapes |
| Webhook / Slack fan-out | `WebhookNotifier.notify_async(WebhookEvent)` | — | ✅ agent-os |
| Transcript / context | `ConversationGuardian.get_transcript(id)`, `ContextScheduler` | — | ✅ agent-os |
| Failure typing | `AgentOSError.error_code` hierarchy (`POLICY_VIOLATION`, `BUDGET_EXCEEDED`, `SECURITY_VIOLATION`, …) | `SecurityFinding(severity, category, …)` | ✅ both |
| Prompt-defense scoring | — | `PromptDefenseEvaluator.evaluate(...)` → `PromptDefenseReport` | ✅ agent-compliance |
| Promotion gate | — | `PromotionChecker.check_promotion(...)` → `PromotionReport` | ✅ agent-compliance |

**Key asymmetry:** agent-os is the *event-driven* layer (publish + subscribe + persist); agent-compliance is a *validator* layer (produce structured findings on demand). The plan treats agent-os as the primary integration target and agent-compliance as a secondary callback that fires from inside agent-os event handlers.

## Per-hook integration matrix

For each missing Claude SDK hook event, the integration is a three-step chain:

```
Claude SDK event  →  policy_engine.adapters.claude factory  →  bus.publish + audit + (optional) compliance call
```

| Claude SDK event | New factory | agent-os primary | agent-compliance secondary |
|---|---|---|---|
| `Stop` | `make_stop_hook(policy, …, *, bus=None, escalator=None)` | `bus.publish("claude.stop", …)` + `audit_logger.log_decision(action="session.stop", decision="ALLOW")` | `PromotionChecker.check_promotion(current=STABLE, …)` if a promotion target was supplied; record any failed gate as audit detail |
| `SubagentStart` | `make_subagent_start_hook(...)` | `bus.publish("claude.subagent.start", parent_agent, child_agent, …)` | (none — no validator gate fits) |
| `SubagentStop` | `make_subagent_stop_hook(...)` | `bus.publish("claude.subagent.stop", …)` + audit row | `PromotionReport.blockers` — append on subagent gate failure |
| `PreCompact` | `make_precompact_hook(...)` | Read `ConversationGuardian.get_transcript(session_id)` if available, archive via `audit_logger`, emit `CHECKPOINT_CREATED` | `PromptDefenseEvaluator.to_audit_entry(report, agent_did)` — produces a hashed-prompt summary record before the SDK throws away history |
| `PostToolUseFailure` | `make_post_tool_failure_hook(...)` | `bus.publish("claude.tool.failure", error_code=…, tool_name=…)` mapped from `AgentOSError` subclasses | `SecurityFinding` if the failure category looks security-relevant (see §"Failure classification") |
| `PermissionRequest` | `make_permission_request_hook(..., escalator)` | `decision = await escalator.request_approval(agent_id, action, context, urgency)` — return SDK `permissionDecision: "allow"|"deny"|"ask"` based on `decision.outcome` | `validate_attestation(pr_body, required_sections)` if context includes a PR ref, to enforce CELA/security review presence |
| `Notification` | `make_notification_hook(..., webhook=None)` | `bus.publish("claude.notification", …)` and (if `webhook` supplied) `webhook.notify_async(WebhookEvent(...))` | `GovernanceAttestation.summary()` for human-readable Slack body when one of agent-compliance's verifiers ran |

The `*` (kwargs only) pattern for the new factories matches the existing `make_user_prompt_hook(policy, *, kernel=None, ctx=None)` signature so nothing breaks: with no integration kwargs, every factory still does the simple thing (record to `policy_engine.audit.AUDIT` and return `{}`).

## Architectural choice: bridge module vs. extra adapter

Three shapes were considered. The plan recommends **option B**.

| Option | Shape | Pros | Cons |
|---|---|---|---|
| A — One file, fat factories | All seven new factories live in `claude.py`, each accepting `bus=`, `escalator=`, `webhook=`, `audit_logger=`, `compliance=` kwargs | Smallest surface; one import; consistent with current adapter | `claude.py` doubles in size; bridges agent-os imports leak into the core "lazy-only-when-used" boundary; harder to test in isolation |
| **B — Sibling bridge module** *(recommended)* | New module `policy_engine.adapters.claude_bridges` exporting `AgentOSBridge` and `AgentComplianceBridge` dataclasses; the seven factories live in `claude.py` and accept a single `bridges=…` kwarg | Keeps `claude.py` lean and SDK-only; bridges lazy-import `agent_os` / `agent_compliance` like the existing `agent_os.py` adapter does; each bridge is independently testable; follows the established `policy-engine[agent-os]` extras pattern | Two new modules instead of one; slightly more surface to document |
| C — Separate full adapters | New `policy_engine.adapters.claude_agent_os` and `policy_engine.adapters.claude_agent_compliance` modules, each re-exporting all factories pre-bound to their backend | Backends are fully independent | Triplicates the factory definitions; bridges are pure plumbing not worth their own adapter modules; users have to pick the right import |

**Recommendation: Option B.** Mirrors what `policy_engine.adapters.agent_os` already does (lazy import inside functions, optional extra in `pyproject.toml`). Keeps the tested `claude.py` boundary intact.

## Files

### Add — `policy-engine/src/policy_engine/adapters/claude_bridges.py`

```python
"""Optional bridges from Claude hook factories to agent-os / agent-compliance.

Lazy-imports both backends so policy-engine core stays stdlib-only.
"""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional


@dataclass
class AgentOSBridge:
    """Wires a Claude hook into agent-os primitives.

    Construction is cheap — the lazy import only happens when the bridge
    is actually invoked. Pass instances of agent-os types you've already
    built, or pass None and let the bridge construct sensible defaults.
    """

    bus: Optional["GovernanceEventBus"] = None
    audit_logger: Optional["GovernanceAuditLogger"] = None
    escalator: Optional["EscalationManager"] = None
    webhook: Optional["WebhookNotifier"] = None
    transcript_source: Optional[Callable[[str], list]] = None  # session_id -> entries

    def publish(self, event_type: str, **data) -> None: ...
    def log(self, agent_id: str, action: str, decision: str, reason: str = "") -> None: ...
    async def request_approval(self, agent_id: str, action: str, context: dict, urgency: str = "medium") -> bool: ...
    def notify(self, event_type: str, agent_id: str, severity: str = "info", **details) -> None: ...
    def archive_transcript(self, session_id: str) -> Optional[list]: ...
    def map_exception(self, exc: BaseException) -> tuple[str, str]:
        """Returns (error_code, severity) — agent_os.AgentOSError if recognized,
        else ("UNKNOWN_ERROR", "medium")."""


@dataclass
class AgentComplianceBridge:
    """Wires a Claude hook into agent-compliance validators.

    All methods return None on missing dep so the bridge is safe to call
    from a Claude hook without conditional logic at the call site.
    """

    agent_did: str = "did:claude:demo"
    promotion_checker: Optional[Any] = None  # PromotionChecker | None
    prompt_defense: Optional[Any] = None     # PromptDefenseEvaluator | None
    required_attestation_sections: list = field(default_factory=list)

    def evaluate_session_for_promotion(self, session_data: dict) -> Optional[dict]: ...
    def hash_and_summarize_prompt(self, prompt: str) -> Optional[dict]: ...
    def validate_pr_attestation(self, pr_body: str) -> Optional[dict]: ...
    def classify_failure(self, error_code: str, message: str) -> Optional[dict]:
        """Returns SecurityFinding-shaped dict if error category is security-relevant."""
```

### Modify — `policy-engine/src/policy_engine/adapters/claude.py`

Add seven new factories. Each has the same shape:

```python
def make_stop_hook(
    policy: GovernancePolicy,
    *,
    kernel: BaseKernel | None = None,
    ctx: ExecutionContext | None = None,
    bridges: list["AgentOSBridge | AgentComplianceBridge"] | None = None,
) -> Callable: ...
```

Hook bodies follow the pattern established by `make_post_tool_use_hook` (informational, no kernel evaluation needed) plus the bridge fan-out. `make_permission_request_hook` is the exception — it awaits the escalator and returns the SDK's `permissionDecision: "allow" | "deny" | "ask"` shape.

Update `__all__` to include the seven new symbols.

### Modify — `policy-engine/pyproject.toml`

Add a new optional extra so users can opt into the bridges:

```toml
[project.optional-dependencies]
claude-bridges = ["agent-os-kernel>=3.2.2,<4", "agent-compliance"]
```

### Add — `policy-engine/tests/test_claude_bridges.py`

Six test classes (one per bridge concern). Each test stubs the agent-os / agent-compliance modules with `unittest.mock` so the suite still runs without those packages installed. Mirrors the no-SDK-import pattern of `tests/test_claude_adapter.py`.

Concrete cases:

1. `test_stop_hook_publishes_and_audits` — feed `AgentOSBridge(bus=fake_bus, audit_logger=fake_logger)`; assert `fake_bus.publish.called_once_with("claude.stop", …)` and audit row appended.
2. `test_subagent_start_and_stop_pair` — fire start then stop; assert `agent_id` correlation in two published events.
3. `test_precompact_archives_transcript_and_summarizes` — `transcript_source` stub returns 3 entries; bridge archives via `audit_logger`; agent-compliance bridge returns a `prompt_hash` dict.
4. `test_post_tool_failure_maps_known_exception_codes` — feed `PolicyViolationError`-shaped dict; assert `error_code="POLICY_VIOLATION"` in published event.
5. `test_permission_request_async_approval_path` — `escalator.request_approval` stub returns `EscalationDecision(outcome=APPROVED)`; hook returns `{"hookSpecificOutput": {…, "permissionDecision": "allow"}}`. Cover deny + timeout cases too.
6. `test_notification_fan_out_to_webhook` — `webhook.notify_async` stub; assert called with a `WebhookEvent`-shaped dict.

### Add — `policy_engine_hello_world_multi_real_consolidated/claude_bridges_demo.py`

A new demo (registered as `claude_bridges` in `run_all.py`) that mirrors `claude_governed.py`'s six-phase shape but adds:

- Phase 0 — build an `AgentOSBridge` with `GovernanceEventBus`, `InMemoryBackend`-backed `GovernanceAuditLogger`, an `EscalationManager` with `default_on_timeout="deny"`, and a `WebhookNotifier` whose URL points at `https://httpbin.org/post` (so the demo exercises the call without depending on a private webhook).
- Phase 7 — print bus event count, audit-logger entry count, and the agent-compliance promotion result. Confirms all three sinks received the same Claude session.

Self-skips like `claude_governed.py` does: missing `CLAUDECODE`, missing SDK, missing auth, missing agent-os.

### Modify — `policy_engine_hello_world_multi_real_consolidated/_shared.py`

Optional small helper `agent_os_optional()` that imports agent-os and returns `None` on `ImportError`, so multiple bridge demos can share one import dance.

### Modify — `policy_engine_hello_world_multi_real_consolidated/run_all.py`

Register `claude_bridges` after the `claude` entry. Use the same skip pattern.

### Modify — `docs/Claude-Agent-SDK-Full-Demo.md` and `docs/Claude-Agent-SDK-Adapter.md`

Cross-link to a new wiki page `Claude-Hooks-Agent-OS-Bridge.md` that documents the bridge module and the seven new factories. Mermaid diagram showing fan-out (Claude → adapter → AgentOSBridge → bus / logger / escalator / webhook → agent-compliance validators).

## Failure classification (the only non-obvious mapping)

`PostToolUseFailure` is the only hook where the mapping requires a small classifier:

```python
# Inside AgentOSBridge.map_exception(exc) — pseudocode
if isinstance(exc, PolicyViolationError):       return ("POLICY_VIOLATION",   "high")
if isinstance(exc, BudgetExceededError):        return ("BUDGET_EXCEEDED",    "medium")
if isinstance(exc, SecurityError):              return ("SECURITY_VIOLATION", "critical")
if isinstance(exc, AdapterTimeoutError):        return ("ADAPTER_TIMEOUT",    "medium")
if isinstance(exc, IdentityVerificationError): return ("IDENTITY_VERIFICATION_FAILED", "high")
if isinstance(exc, AgentOSError):               return (exc.error_code,       "medium")
return ("UNKNOWN_ERROR", "medium")
```

`AgentComplianceBridge.classify_failure(error_code, message)` returns a `SecurityFinding`-shaped dict only when `severity in ("critical", "high")` and the `category` matches `("secrets", "cve", "code-pattern")` substring heuristics on the message. Otherwise returns `None` — the agent-os event publication is sufficient.

## End-to-end shape

```
+----------------------+       +------------------------+
|  Claude Agent SDK    |       |   policy_engine.audit  |
|  (Stop, PreCompact,  |       |       AUDIT list       |
|   ...)               |       |   (always written)     |
+----------+-----------+       +-----------+------------+
           |                               ^
           v                               |
+----------------------+    +--------------+--------------+
| policy_engine        |    |   one row per hook event    |
| .adapters.claude     |--->|   shared with all 7 demos   |
| make_stop_hook(...)  |    +-----------------------------+
+----------+-----------+
           |
           | bridges=[AgentOSBridge(...), AgentComplianceBridge(...)]
           v
+----------------------+        +-------------------------+
| AgentOSBridge        |        | AgentComplianceBridge   |
|  - bus.publish       |        |  - prompt_defense       |
|  - audit_logger.log  |        |  - promotion_checker    |
|  - escalator.approve |        |  - validate_attestation |
|  - webhook.notify    |        |  - classify_failure     |
|  - transcript_source |        +-----------+-------------+
+----------+-----------+                    |
           |                                v
           v                    +-------------------------+
+----------------------+        | findings dataclasses    |
| agent-os runtime     |        | (SecurityFinding,       |
|  - GovernanceEventBus|<-------| PromotionReport, ...)   |
|  - WebhookNotifier   |  feed  +-------------------------+
|  - AuditLogger       |
+----------------------+
```

## Verification

1. **Unit tests (no agent-os, no agent-compliance, no SDK):**
   ```
   cd policy-engine && python -m pytest tests/test_claude_bridges.py -v
   ```
   All bridge tests pass with stubbed backends.

2. **With agent-os installed:**
   ```
   pip install -e ../agent-os
   python -m pytest tests/ -v
   ```
   Bridge tests still pass; new lazy-import paths exercised.

3. **Bridge demo skip path:**
   ```
   python policy_engine_hello_world_multi_real_consolidated/run_all.py --only claude_bridges
   ```
   Without `claude-agent-sdk` → `[skip] missing dependency`. Without `CLAUDECODE` unset → demo runs.

4. **Bridge demo full path** (auth + SDK + agent-os installed):
   - Bus history contains at least: `claude.stop`, `claude.subagent.*` (if Claude spawned a subagent), `claude.tool.failure` (if any tool errored), `claude.notification`.
   - Audit-logger backend has a row for every hook event.
   - Webhook stub at `httpbin.org/post` returns 200 for `Notification` events.
   - The Phase 6 audit summary in `claude_governed.py` plus the Phase 7 bridge summary in `claude_bridges_demo.py` together account for every Claude event without duplication.

5. **Cross-check with the unified summary:**
   ```
   python policy_engine_hello_world_multi_real_consolidated/run_all.py
   ```
   Total `claude` rows in the audit trail = (UserPromptSubmit + PreToolUse + PostToolUse from `claude_governed`) + 7 bridge phases from `claude_bridges_demo`. No other framework's row count changes.

## Out of scope (explicit non-goals)

- TypeScript-only Claude SDK events (`SessionStart`, `SessionEnd`, `Setup`, `TeammateIdle`, `TaskCompleted`, `ConfigChange`, `WorktreeCreate`, `WorktreeRemove`, `PostToolBatch`). Adding these would require a TS adapter; this plan stays Python-only.
- Persisting bus events past the in-memory `InMemoryBackend`. The plan demos `JsonlFileBackend` in passing but doesn't make it the default — that's a deployment choice, not an integration choice.
- A new agent-compliance entrypoint. The plan only consumes existing agent-compliance dataclasses; it doesn't add validators to that package.
- Replacing the existing `policy_engine.adapters.agent_os.AgentOSKernel`. That facade stays as the `pre_execute` gate; the new bridges sit *next to* it on the lifecycle/event surface.

## See also

- [[Claude-Agent-SDK-Adapter]] — SDK reference (event names, options)
- [[Claude-Agent-SDK-Full-Demo]] — current `claude_governed.py` architecture
- [[Agent-OS-Backend-Adapter]] — existing AgentOSKernel facade for `pre_execute`
- [[Seam-Taxonomy]] — how this fits the broader adapter shape
