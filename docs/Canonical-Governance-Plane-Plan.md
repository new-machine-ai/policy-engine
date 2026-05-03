# Plan: Canonical Governance Plane Refactor

## Context

Today the policy-engine ships as a `BaseKernel.evaluate(ctx, PolicyRequest) -> PolicyDecision` gate that 8 adapters call from their framework's native seams. Each adapter file is small, but the *set* of seams is wildly uneven:

| Adapter | Seams wired today | Canonical events naturally available |
|---|---|---|
| `claude.py` | 10 (UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, Stop, SubagentStart/Stop, PreCompact, PermissionRequest, Notification) | 8 of 9 (no `model.response`) |
| `maf.py` | 1 middleware gate (phase = `pre_execute`/`tool_call`) | 4 of 9 |
| `crewai.py` | 2 (`@before_llm_call`, `@after_llm_call`) | 2 of 9 |
| `langchain.py` | 1 (`pre_model_hook`) | 1 of 9 |
| `openai_assistants.py` | 1 (`add_message` proxy) | 1 of 9 |
| `openai_agents.py` | 1 (`Runner.run` wrap) | 1 of 9 |
| `pydantic_ai.py` | 1 (`Agent.run` wrap) | 1 of 9 |
| `agent_os.py` | 0 framework seams (policy backend only) | 2 of 9 |

The canonical vocabulary the user wants — `model.request`, `model.response`, `tool.proposed`, `tool.approved`, `tool.executed`, `tool.result`, `run.interrupted`, `run.resumed`, `state.snapshotted` — is mostly *available* in the underlying frameworks but unwired in our adapters. Today's `audit.AUDIT` records are flat tuples (`framework, phase, status, detail`) with no correlation ID, no parent-event linkage, and a phase string that varies per adapter, so a downstream consumer cannot say "give me every `tool.proposed` event regardless of framework."

The product framing should match this: the engine is a **canonical event-and-policy plane**, not a per-framework plugin pack. Adapters become translators that map native hooks → shared event vocabulary; policies subscribe to canonical event types instead of framework-specific phases.

## Recommended approach: additive event layer + phased adapter migration

Introduce a canonical event model alongside the existing `evaluate(PolicyRequest)` API. Wire `audit()` and `BaseKernel.evaluate` as the first two subscribers so today's behavior is preserved bit-for-bit. Then migrate adapters one at a time, richest first (Claude → MAF → CrewAI → the rest). Drop the legacy phase strings only after every adapter has shipped canonical events and downstream demos have been switched.

### Pros

- **Backward compatible.** The 7 demo files, the `run_all.py` audit summary, both test files, and any external pin on `audit.AUDIT[i]["phase"]` keep working. We can land the bus before any adapter changes.
- **Splits notification from gating.** Today `kernel.evaluate` is both "audit this" and "decide allow/deny." The canonical model lets a policy subscribe to `tool.proposed` for a deny vote *and* a telemetry exporter subscribe to the same event for fan-out, with no coupling.
- **Surfaces the coverage gap honestly.** The canonical event set makes "LangChain only emits 1 of 9 events today" a measurable, fixable gap rather than a hidden asymmetry.
- **Lets richer adapters lead.** Claude already covers 8/9 events natively — migrating it first proves the whole vocabulary on a single framework before we touch the thin adapters.
- **No daylight between core and `agent_os`.** The bridge adapter can be re-expressed as "subscribe to `tool.proposed` and delegate to Agent-OS PolicyInterceptor" rather than re-implementing the kernel.

### Cons

- **Two APIs coexist during migration.** Contributors have to know whether to call `kernel.evaluate(request)` or `bus.emit(event)`. We mitigate by having `evaluate()` internally emit `tool.proposed` / `model.request` so they're not parallel paths — `evaluate` becomes a thin convenience over `emit`.
- **Risk of stalling at "additive."** If migration momentum dies after Claude, we'd be left with a richer Claude path and untouched thin adapters — i.e., the same asymmetry, just dressed differently. We mitigate by sizing each adapter migration as a single PR and treating any uncovered event as `unavailable` (typed) rather than `not-yet-implemented` (unbounded).
- **Sync vs async fragmentation.** Claude hooks are async; LangChain `pre_model_hook` and CrewAI decorators are sync; MAF middleware is async. The bus needs `emit` (sync) and `aemit` (async); subscribers must declare which they support. This is one extra concept readers must understand.
- **Audit shape grows.** Adding `event_type`, `correlation_id`, `parent_event_id`, `event_id` to records means demos that print the audit table need a one-line format update, and any external consumer pinning the dict shape will need to opt into the richer fields.
- **`run.interrupted` / `run.resumed` are aspirational for most frameworks today.** Only LangGraph interrupts and Claude's `Stop` come close, and Claude's `Stop` is informational. We'll ship those event types in the vocabulary but document them as `unavailable` for 6 of 8 adapters initially.

## Architecture

```
                            +---------------------+
   framework hook  ──────►  |  Adapter            |
   (e.g., PreToolUse)       |  translates native  |
                            |  surface to canonical|
                            |  Event              |
                            +---------+-----------+
                                      │ bus.emit(event)
                                      ▼
                            +---------------------+
                            |  EventBus           |
                            |  fan-out by         |
                            |  event_type         |
                            +---------+-----------+
                          ┌──────────┼──────────┐
                          ▼          ▼          ▼
                    GatePolicy   AuditSink   Telemetry
                    (returns    (writes      (forwards to
                     Decision)    AUDIT)      OTel etc.)
```

A handler returning `PolicyDecision(allowed=False, ...)` short-circuits the bus for that event; the adapter sees the deny and translates it back to its framework's native refusal shape (raise, return `permissionDecision="deny"`, etc.).

## Canonical event vocabulary

| Event | When fired | Typical payload keys | Gating? |
|---|---|---|---|
| `model.request` | Before an LLM call | `messages`, `model_name`, `tools_advertised` | yes |
| `model.response` | After an LLM call returns | `output`, `usage`, `finish_reason` | optional |
| `tool.proposed` | LLM has chosen a tool but not run it | `tool_name`, `args`, `model_name` | yes |
| `tool.approved` | A gate has cleared a `tool.proposed` (or human approved) | `tool_name`, `args`, `approver` | no |
| `tool.executed` | Tool runtime invoked | `tool_name`, `args`, `started_at` | no |
| `tool.result` | Tool runtime returned (success or error) | `tool_name`, `result`, `error`, `duration_ms` | no |
| `run.interrupted` | Run paused (human-in-the-loop, breakpoint, error) | `reason`, `resumable` | no |
| `run.resumed` | Run resumed after interrupt | `reason`, `original_event_id` | no |
| `state.snapshotted` | Conversation/agent state checkpointed (e.g., compaction) | `snapshot_id`, `size_bytes`, `trigger` | no |

## Concrete changes

### New files

- `policy-engine/src/policy_engine/events.py` — `Event` dataclass (`event_type: str`, `event_id: str`, `correlation_id: str`, `parent_event_id: str | None`, `framework: str`, `timestamp: datetime`, `payload: dict`), plus a typed registry of the 9 canonical event names as constants.
- `policy-engine/src/policy_engine/bus.py` — `EventBus` with `subscribe(event_type, handler, *, gating: bool = False)`, `emit(event) -> PolicyDecision | None`, `aemit(event) -> PolicyDecision | None`. First gating handler that returns a deny short-circuits; non-gating handlers always all run; one handler raising never stops fan-out (errors caught, audited as `handler_error`).
- `policy-engine/tests/test_events.py` — fanout, ordering, gate short-circuit, error isolation, sync vs async parity.

### Modified files

- `policy-engine/src/policy_engine/audit.py` (lines 9–44) — keep current `audit()` signature; add `audit_from_event(event, decision)` that maps a canonical event to today's flat record. Default-subscribe both legacy `audit` and `audit_from_event` to the bus on import so `AUDIT` keeps filling without per-adapter changes.
- `policy-engine/src/policy_engine/policy.py` (lines 8–26) — add `Event.from_policy_request(req, ctx)` and `PolicyRequest.from_event(event)` constructors. No field changes; new types live in `events.py`.
- `policy-engine/src/policy_engine/kernel.py` (lines 17–71) — `BaseKernel.evaluate` becomes: build an `Event` (`tool.proposed` if `request.tool_name`, else `model.request`), call `bus.emit`, fall through to today's pattern/quota logic if no gating handler decided. The default gating handler IS today's evaluate body, registered on `__init__`.
- `policy-engine/src/policy_engine/__init__.py` — export `Event`, `EventBus`, `EVENT_TYPES`, `subscribe`, plus today's surface unchanged.

### Adapter migration order (one PR each)

1. **`adapters/claude.py`** — already wires 10 hooks; rewrite the 10 factory closures so each emits its corresponding canonical event before/after calling `kernel.evaluate`. PostToolUse → `tool.executed`; PostToolUseFailure → `tool.result` (with `error`); PreCompact → `state.snapshotted`. This PR alone proves 8/9 events.
2. **`adapters/maf.py`** — split the single `_policy_gate` middleware into "emit `model.request` when no tool_name" and "emit `tool.proposed` when there is one"; add a post-step middleware that emits `model.response`. Keeps the existing seam, just labels what it's doing.
3. **`adapters/crewai.py`** — `@before_llm_call` → `model.request`, `@after_llm_call` → `model.response`. If CrewAI gains tool hooks (it currently doesn't expose any), wire them then.
4. **`adapters/langchain.py`** — `pre_model_hook` → `model.request`. Investigate `langgraph.types.interrupt` and the prebuilt agent's tool-node hooks for `tool.proposed` and `run.interrupted`.
5. **`adapters/openai_assistants.py`** — `add_message` → `model.request`; if/when the run-step polling loop is wrapped, emit `tool.proposed`/`tool.executed` from the run-step inspection.
6. **`adapters/openai_agents.py`** — `Runner.run` input → `model.request`; the SDK's `RunHooks` lifecycle gives us `model.response` and `tool.proposed`/`tool.executed` if we register them in the wrapper instead of leaving them to the demo.
7. **`adapters/pydantic_ai.py`** — `Agent.run` prompt → `model.request`. PydanticAI's tool-call decorators can wrap `tool.proposed`/`tool.result`; investigate during the PR.
8. **`adapters/agent_os.py`** — re-express as a gating subscriber on `tool.proposed` and `model.request` rather than a `BaseKernel` subclass that overrides `evaluate`. Same external behavior, but it stops competing with the canonical kernel.

### Demos / docs

- `policy_engine_hello_world_multi_real_consolidated/_shared.py` — add `bus = EventBus()` to the shared module so the per-framework demos all share one fan-out.
- `policy_engine_hello_world_multi_real_consolidated/governance_showcase.py` — extend the existing showcase to print "events emitted: X" alongside the policy decisions, demonstrating the fan-out story.
- New `policy_engine_hello_world_multi_real_consolidated/canonical_events_demo.py` — one shared policy class that subscribes to `tool.proposed`, run across all adapters in sequence, showing the same handler firing on every framework that emits the event.
- [[Seam-Taxonomy]] already exists as a per-adapter table — extend it with a "Canonical event coverage" column matching the survey table above.
- `CLAUDE.md` Architecture section — replace the four-pattern adapter table with a "translates which native hooks → which canonical events" table once migration is complete.

## Verification

1. **Unit:** `pytest policy-engine/tests/test_events.py policy-engine/tests/test_policy.py policy-engine/tests/test_claude_adapter.py` — bus fanout, gate short-circuit, error isolation, plus existing tests pass unchanged.
2. **Behavioral parity (per adapter PR):** Before merging an adapter migration, snapshot today's `AUDIT` from `python policy_engine_hello_world_multi_real_consolidated/run_all.py --only <demo-key>`, then re-run after the change. The `(framework, phase, status, detail)` tuples must match (the legacy subscriber preserves them). Diff with `diff <(python ... | grep AUDIT) <(...)`.
3. **Cross-framework demo:** `python policy_engine_hello_world_multi_real_consolidated/canonical_events_demo.py` should show one policy class catching `tool.proposed` events from at least Claude, MAF, and Agent-OS in a single run with consistent payload shape.
4. **Coverage matrix doc:** [[Seam-Taxonomy]] updated row-by-row as each adapter ships; the table is the migration tracker.

## Critical files

- `policy-engine/src/policy_engine/audit.py` (lines 9–44) — must keep `audit()` signature stable.
- `policy-engine/src/policy_engine/policy.py` (lines 8–26) — `PolicyRequest`/`PolicyDecision` field stability matters for downstream pins.
- `policy-engine/src/policy_engine/kernel.py` (lines 17–71) — the legacy `evaluate` body becomes the default gating subscriber.
- `policy-engine/src/policy_engine/adapters/claude.py` (10 factories at lines 56–382) — the proof point for the canonical vocabulary.
- `policy-engine/src/policy_engine/adapters/agent_os.py` (lines 96–198) — the cleanest payoff: stops being a `BaseKernel` override and becomes a regular subscriber.

## Out of scope

- Persistent event store / replay log. The bus stays in-memory; persistence is a separate ticket and belongs in the `agent_os` integration if anywhere.
- Distributed bus / cross-process fan-out. Same subprocess only.
- Schema versioning of `Event.payload`. We'll document field names per event type but not wire a schema validator yet.
- Removing `kernel.pre_execute`. Stays as the tuple-returning compatibility wrapper.

## Related pages

- [[Home]] — wiki landing page
- [[Core-Concepts]] — current `BaseKernel`/`PolicyDecision` model
- [[Seam-Taxonomy]] — per-adapter seam table (will gain a canonical-event column during migration)
- [[Claude-Agent-SDK-Adapter]] — first migration target; covers 8/9 canonical events natively
- [[Agent-OS-Backend-Adapter]] — last migration target; will become a gating subscriber
