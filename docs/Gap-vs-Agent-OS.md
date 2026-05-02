# Gap analysis: policy-engine vs. agent-os / agentmesh

This page compares **`policy-engine`** (this repo — a stdlib-only governance
kernel) against the **`agent-os` + `agent-mesh` + `langchain-agentmesh`**
stack in the sibling repo
`agent-governance-toolkit/agent-governance-python/`. It is driven by a
concrete question: *what would we have to add to `policy-engine` to run
the LangChain notebook
[`04_langchain_agentmesh_chatbot.ipynb`](https://github.com/microsoft/agent-governance-toolkit/blob/main/notebooks/04_langchain_agentmesh_chatbot.ipynb)?*

Spoiler: most of it. The two projects come from different governance
traditions. `policy-engine` is intentionally minimal — five fields on a
`GovernancePolicy` and one `evaluate()` call. `agent-os` is a multi-package
ecosystem that bundles cryptographic identity, signed agent cards, trust
scoring, delegation chains, replay-attack prevention, token-bucket rate
limiting, egress policies, prompt-injection defenses, content quality
gates, MCP auth enforcement, and more.

> Companion pages: [[Core-Concepts]] for our kernel mechanics;
> [[Demos]] for what runs on the current surface;
> [[Agent-OS-Backend-Adapter]] for the existing bridge that delegates
> to `agent-os-kernel`'s `PolicyInterceptor`.

## TL;DR

| Capability | policy-engine | agent-os / agentmesh | Notebook needs it? |
|---|---|---|---|
| Pattern blocking on prompts | Substring (case-insensitive) | Regex + ML classifiers (`prompt_injection.py`) | Indirect (system prompt only) |
| Tool allow/deny | `allowed_tools` / `blocked_tools` lists | Capability tokens + min-trust per tool | **Yes** |
| Rate limiting | `max_tool_calls` (single int cap) | `TokenBucket(capacity, refill_rate)` | **Yes** |
| Human approval | `require_human_approval` bool | Trust handshake + escalation graph | No |
| Cryptographic identity | None | `VerificationIdentity` (Ed25519, DID) | **Yes** |
| Signed agent credentials | None | `TrustedAgentCard.sign()` / `.verify_signature()` | **Yes** |
| Trust scoring | None | `trust_score: float` (0.0–1.0) per card | **Yes** |
| Delegation / scope chains | None | `Delegation` + signature replay protection | No (single agent) |
| Audit trail | `AUDIT` list of dicts; payload **SHA-256 hashed** | `ToolInvocationRecord`; payload **stored truncated to 200 chars plaintext** | **Yes** (different shape) |
| LangChain integration | `LangChainKernel.as_middleware()` (model-call seam) | `TrustGatedTool` wrapper (tool-call seam) | **Yes** |
| MCP auth enforcement | None | `mcp_auth_enforcement.py` | No |
| Egress (network) policy | None | `egress_policy.py` | No |
| Circuit breaker | None | `circuit_breaker.py` | No |
| Content quality gates | None | `content_governance.py` | No |
| Context / token budgets | None | `context_budget.py` | No |
| Credential redaction | None | `credential_redactor.py` | No |
| Adversarial / fuzzing | None | `adversarial.py`, `fuzz/` | No |
| Backend bridges (Cedar, OPA) | None | `policies/backends.py` | No |
| **Heavy deps** | **stdlib only** | `cryptography`, `pydantic`, `rich`, optional `pynacl`, `fastapi`, `prometheus`, etc. | n/a |

Three cells of the notebook fail before reaching the LLM if you swap
in `policy-engine`: identity creation, trust-gated tool wrapping, and
rate-bucket setup. The kernel call itself (`evaluate`) would still
work for the prompt-pattern part, but the rest of the demo
disappears.

---

## What `policy-engine` actually ships

The whole engine is ~150 lines of stdlib Python.

```python
# policy-engine/src/policy_engine/policy.py
@dataclass
class GovernancePolicy:
    name: str = "default"
    blocked_patterns: list[str] = field(default_factory=list)   # substring match
    max_tool_calls: int = 10                                    # one-shot cap
    require_human_approval: bool = False
    allowed_tools: list[str] | None = None
    blocked_tools: list[str] | None = None
```

```python
# policy-engine/src/policy_engine/kernel.py
class BaseKernel:
    def evaluate(self, ctx: ExecutionContext, request: PolicyRequest | str) -> PolicyDecision:
        # Fixed order:
        # 1. ctx.call_count >= policy.max_tool_calls -> deny
        # 2. tool_name in blocked_tools / not in allowed_tools -> deny
        # 3. policy.require_human_approval -> deny + requires_approval=True
        # 4. policy.matches_pattern(payload) -> deny + matched_pattern
        # 5. ctx.call_count += 1; allow
```

```python
# policy-engine/src/policy_engine/audit.py
def audit(framework, phase, status, detail="", *,
          decision=None, policy=None, reason=None,
          tool_name=None, payload_hash=None) -> None: ...
# Each AUDIT entry:
#   {ts, framework, phase, status, detail,
#    policy?, reason?, tool_name?, payload_hash?}
# Raw payload is NEVER stored; only SHA-256.
```

That's the whole surface. Adapters in `policy_engine.adapters.*`
plug this `evaluate()` into different SDK seams (LangChain
middleware, Claude SDK hooks, Anthropic client wrap, etc.) but they
don't extend the policy model itself.

## What the agentmesh notebook ships against

The notebook imports from two PyPI packages outside this repo:

```python
# from agentmesh-integrations/langchain-agentmesh/
from langchain_agentmesh import (
    VerificationIdentity, TrustedAgentCard,
    TrustGatedTool, TrustPolicy, TrustedToolExecutor,
)
# from agent-os/src/agent_os/policies/
from agent_os.policies.rate_limiting import RateLimitConfig, TokenBucket
```

Each is a real, sizable subsystem:

- `agent_os_kernel` (PyPI) — depends on `pydantic>=2.4`, `rich`,
  optionally `pynacl`, `fastapi`, `cryptography`, `prometheus`,
  `opentelemetry`. Contains rate limiting, audit logging, circuit
  breaker, content governance, egress policy, execution context,
  MCP auth, prompt-injection detection, ~30 modules.
- `agentmesh_langchain` (PyPI) — depends on
  `langchain-core>=1.2.28` and `cryptography>=45.0.3`. Contains
  identity, trust handshake, delegation chains, agent cards, the
  `TrustGatedTool` wrapper, and `TrustedToolExecutor`.

---

## Per-capability gap

### 1. Cryptographic identity — **missing**

**Their API** (`agentmesh-integrations/langchain-agentmesh/langchain_agentmesh/identity.py:72-146`):

```python
@dataclass
class VerificationIdentity:
    did: str                            # "did:verification:{sha256_hash[:32]}"
    agent_name: str
    public_key: str                     # base64 Ed25519
    private_key: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    created_at: datetime = ...
    expires_at: Optional[datetime] = None

    @classmethod
    def generate(cls, agent_name: str,
                 capabilities: Optional[List[str]] = None,
                 ttl_seconds: Optional[int] = None) -> "VerificationIdentity": ...

    def sign(self, data: str) -> VerificationSignature: ...
    def verify_signature(self, data: str, signature: VerificationSignature) -> bool: ...
    def is_expired(self) -> bool: ...
    def public_identity(self) -> "VerificationIdentity": ...  # strips private key
```

Backend: `cryptography.hazmat.primitives.asymmetric.ed25519`. Falls
back to a SHA-256 HMAC stub if `cryptography` is missing
(dev-only, not secure).

**Our equivalent:** none. `policy-engine` has no concept of agent
identity — `ExecutionContext.name` is just a string label for the
audit trail.

**To match, we would need:**

- A new `policy_engine.identity` module wrapping
  `cryptography.hazmat.primitives.asymmetric.ed25519`.
- Make `cryptography` an optional extra (`policy-engine[identity]`)
  so the stdlib-only core stays stdlib-only.
- Decide on a DID format. Reusing `did:verification:<hash>` keeps us
  interoperable with agentmesh; inventing our own format isolates us.
- Optional TTL + `is_expired()`.

**Effort:** moderate. ~150 lines + tests. Real risk is committing to
a key-management story (rotation, persistence, secure storage) we
don't currently have.

### 2. Signed agent cards — **missing**

**Their API** (`langchain_agentmesh/trust.py:108-211`):

```python
@dataclass
class TrustedAgentCard:
    name: str
    description: str
    capabilities: List[str]
    identity: Optional[VerificationIdentity] = None
    trust_score: float = 1.0                      # 0.0–1.0
    card_signature: Optional[VerificationSignature] = None
    scope_chain: Optional[List["Delegation"]] = None
    user_context: Optional[UserContext] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def sign(self, identity: VerificationIdentity) -> None: ...
    def verify_signature(self) -> bool: ...
    def to_json(self) -> str: ...
    @classmethod
    def from_json(cls, payload: str) -> "TrustedAgentCard": ...
```

Notebook usage:

```python
bot_identity = VerificationIdentity.generate(
    "support-chatbot",
    capabilities=["lookup_order", "check_inventory", "cancel_account", "update_shipping"],
)
bot_card = TrustedAgentCard(
    name="Support Chatbot",
    description="...",
    capabilities=[...],
    trust_score=0.7,
)
bot_card.sign(bot_identity)
assert bot_card.verify_signature()
```

The signed payload is a deterministic JSON
(`json.dumps(content, sort_keys=True, separators=(",", ":"))`) of
`{name, description, capabilities, trust_score, identity_did,
identity_public_key}`.

**Our equivalent:** none. We have `GovernancePolicy.name` as a
free-text label; no notion of "this agent presents these credentials."

**To match, we would need:**

- `TrustedAgentCard`-equivalent dataclass.
- Deterministic JSON canonicalization (sort_keys + minimal separators).
- A `card.sign(identity)` flow that depends on the identity work above.
- A schema decision: trust_score range, capability syntax, scope-chain
  format. The agentmesh schema is the path of least friction if we want
  interop.

**Effort:** small once identity exists (~100 lines), but it forces
the schema decisions above.

### 3. Capability + trust-gated tool wrapping — **missing**

**Their API** (`langchain_agentmesh/tools.py:40-133`):

```python
class TrustGatedTool:
    def __init__(self,
                 tool: Union[BaseTool, Callable],
                 required_capabilities: Optional[List[str]] = None,
                 min_trust_score: float = 0.7,
                 description_suffix: str = ""): ...

    def can_invoke(self, invoker_card, handshake) -> TrustVerificationResult: ...
    def invoke(self, invoker_card, handshake, *args, **kwargs):  # raises PermissionError
```

Notebook usage:

```python
gated_tools = [
    TrustGatedTool(tool=lookup_order,    required_capabilities=["lookup_order"],    min_trust_score=0.5),
    TrustGatedTool(tool=cancel_account,  required_capabilities=["cancel_account"],  min_trust_score=0.95),
    TrustGatedTool(tool=process_refund,  required_capabilities=["process_refund"],  min_trust_score=0.5),
]
```

Decision logic per tool: presented card must (a) verify signature,
(b) include all `required_capabilities`, (c) have
`trust_score >= min_trust_score`.

**Our nearest equivalent** — coarse-grained tool allow/deny:

```python
policy = GovernancePolicy(
    name="bot",
    blocked_tools=["cancel_account", "process_refund"],   # binary; no per-tool trust
)
kernel = BaseKernel(policy)
ctx = kernel.create_context("bot")
decision = kernel.evaluate(ctx, PolicyRequest(payload="...", tool_name="cancel_account"))
# decision.allowed == False, decision.reason == "blocked_tool:cancel_account"
```

This collapses the agentmesh notebook's two scenarios
("missing capability" vs "trust too low") into one
("not in allowlist"). The reason string is also less informative.

**To match, we would need:**

- `RequiredCapability(token: str, min_trust: float)` annotation per
  tool.
- A new `PolicyRequest` field `invoker_card: TrustedAgentCard` (or a
  callback that resolves it).
- Extend `BaseKernel.evaluate` to check
  (a) card signature, (b) capability set, (c) trust score per tool —
  in addition to the existing fixed order.
- A new reason string per failure mode
  (`missing_capability:cancel_account`,
  `trust_too_low:cancel_account:0.7<0.95`).

**Effort:** moderate. The policy model gets a second dimension
(per-tool requirements rather than global allowlists), and the
existing adapters all need to know how to surface the `invoker_card`
to the kernel.

### 4. Token-bucket rate limiting — **missing**

**Their API** (`agent-os/src/agent_os/policies/rate_limiting.py:27-143`):

```python
@dataclass(frozen=True)
class RateLimitConfig:
    capacity: float
    refill_rate: float
    initial_tokens: float | None = None

@dataclass
class TokenBucket:
    capacity: float
    tokens: float
    refill_rate: float
    last_refill: float = field(default_factory=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock, ...)

    @classmethod
    def from_config(cls, config: RateLimitConfig) -> "TokenBucket": ...
    def consume(self, tokens: float = 1.0) -> bool: ...   # thread-safe
    @property
    def available(self) -> float: ...                      # refills + returns
    def time_until_available(self, tokens: float = 1.0) -> float: ...
    def reset(self, tokens: float | None = None) -> None: ...
```

Refill algorithm: `tokens = min(capacity, tokens + elapsed * refill_rate)`,
recomputed on every call. Thread-safe via `threading.Lock`.

Notebook usage:

```python
rate_config = RateLimitConfig(capacity=5, refill_rate=1.0)
rate_bucket = TokenBucket.from_config(rate_config)
if not rate_bucket.consume():
    return f"Wait ~{rate_bucket.time_until_available():.1f}s"
```

**Our nearest equivalent** — a one-shot integer cap on `ExecutionContext.call_count`:

```python
policy = GovernancePolicy(name="bot", max_tool_calls=5)
kernel = BaseKernel(policy)
ctx = kernel.create_context("bot")
for _ in range(6):
    decision = kernel.evaluate(ctx, PolicyRequest(payload="x"))
# decision.reason == "max_tool_calls exceeded" on the 6th call
# ctx never refills; the only way to "reset" is to make a new ExecutionContext
```

The two algorithms do different things:

- `max_tool_calls` is "lifetime cap per context." Once you hit it,
  every subsequent call denies until the context is recreated.
- `TokenBucket` is "burst of N, refilling 1 every X seconds." It's
  designed for sustained throughput with bursts.

**To match, we would need:**

- A new `policy_engine.rate_limit` submodule with `RateLimitConfig`
  and `TokenBucket` (port directly — the algorithm is small and
  stdlib-friendly; uses only `time.monotonic` and `threading.Lock`).
- Extend `GovernancePolicy` with an optional `rate_limit:
  RateLimitConfig | None` field.
- Have `BaseKernel.evaluate` consume from the bucket *before*
  incrementing `call_count`, with a new reason string
  (`rate_limited:wait_until=<float>`).
- Decide whether to keep `max_tool_calls` (lifetime) alongside
  `rate_limit` (refilling) or deprecate one. Both serve different
  use cases — keep both.

**Effort:** small. The whole port is ~50 lines of code + tests, and
it's the one piece the agent-os ecosystem itself ships as a
self-contained module under `agent_os/policies/rate_limiting.py`. We
could even re-export theirs by adding `agent-os-kernel` to an
optional extra (`policy-engine[rate-limiting]`) instead of
re-implementing.

### 5. Trust handshake & cache — **missing**

`TrustedToolExecutor` keeps a `_verified_peers` cache keyed by DID,
expiring after `TrustPolicy.cache_ttl_seconds` (default 900s = 15
min). It also tracks replay windows
(`replay_window_seconds=300`), clock skew tolerances
(`max_signature_clock_skew_seconds=60`), and per-DID rate limits
(`max_scope_chain_attempts_per_window=120`).

Most of this is plumbing for multi-agent delegation (agents
introducing other agents). The notebook uses a single agent, so the
handshake collapses to a one-shot signature verification — but the
machinery is wired in.

**Our equivalent:** none. We don't have a multi-agent model.

**To match, we would need:**

- A `TrustHandshake` object with replay-window + clock-skew checks.
- The cache layer above.
- All of this only matters if we add identity + cards in the first
  place; it's the third floor of the pyramid.

**Effort:** large. Skip unless we commit to the full identity story.

### 6. LangChain wiring — **partial**

We already ship a LangChain adapter:

```python
# policy_engine/adapters/langchain.py
class LangChainKernel(BaseKernel):
    framework = "langchain"
    def as_middleware(self, *, name: str = "langchain") -> AgentMiddleware:
        # Returns an AgentMiddleware whose before_model() runs
        # kernel.evaluate(ctx, PolicyRequest(payload=last_user_message))
        # before the LLM is called.
```

It hooks at the `before_model` seam — *before* the LLM decides
which tool to call. The agentmesh notebook hooks at the *individual
tool wrapper* seam, *after* the LLM has chosen but *before* the tool
runs. Both are valid but answer different questions.

**Our seam** answers "should this prompt reach the LLM at all?"
**Their seam** answers "should this LLM-chosen tool actually
execute?"

**To match the notebook's flow,** we'd need either:

- A `TrustGatedTool`-equivalent wrapper around individual LangChain
  `@tool` callables, which calls `kernel.evaluate(ctx,
  PolicyRequest(tool_name=, payload=tool_input))` inside the wrapper
  body. ~30 lines.
- Plus the upstream identity / capability / trust-score work to make
  the wrapper's decision interesting.

**Effort:** trivial for the wrapper, blocked on the identity stack.

### 7. Audit trail shape — **different on purpose**

Ours:

```python
{
    "ts": "2026-05-02T...+00:00",
    "framework": "langchain",
    "phase": "before_model",
    "status": "BLOCKED",
    "detail": "...",
    "policy": "lite-policy",
    "reason": "blocked_pattern:DROP TABLE",
    "tool_name": None,
    "payload_hash": "01367c0db1fb3c64...",   # SHA-256, raw payload absent
}
```

Theirs (`langchain_agentmesh/tools.py:25-38`):

```python
@dataclass
class ToolInvocationRecord:
    tool_name: str
    invoker_did: Optional[str]
    timestamp: datetime
    verified: bool
    trust_score: float
    input_summary: str        # str(input_data)[:200]  -- TRUNCATED PLAINTEXT
    result_summary: str       # str(result)[:200]      -- TRUNCATED PLAINTEXT
    user_context: Optional[UserContext] = None
    warnings: List[str] = field(default_factory=list)
```

**Privacy contrast:** ours is privacy-respecting by default (only
the SHA-256 hash crosses the audit boundary). Theirs stores the
first 200 characters of input and result in plaintext, which leaks
PII / credentials unless wrapped by their separate
`credential_redactor.py`.

**To match the notebook's expectations,** we'd need:

- A `to_invocation_record()` adapter that materializes our audit dict
  into their `ToolInvocationRecord` shape — necessary if we want our
  output to drop into agentmesh dashboards.
- An *optional* mode where the engine includes a truncated-plaintext
  `payload_summary` alongside `payload_hash`. We should think hard
  before adding this — it's a deliberate non-feature today, and
  flipping the default would be a regression.

**Effort:** trivial code change (~20 lines), high design risk.

### 8. Pattern blocking — close, but theirs is richer

Ours: `policy.blocked_patterns` is case-insensitive substring
match (see `policy.py:50-57`). Five lines of code.

Theirs: `agent_os/prompt_injection.py` ships an OWASP LLM01–style
detector with regex + ML classifiers covering override patterns,
delimiter attacks, encoding tricks (base64/rot13), jailbreak
templates, and canary-leak detection. Substantially more sophisticated.

**To match,** we'd need to swap our 5-line substring matcher for
something with regex + heuristics. Not strictly required for the
notebook (its system prompt is the only thing that hits the
matcher) but a clear weakness if we ever care about prompt-injection
defense.

**Effort:** if we just want regex, ~10 lines. If we want their full
heuristic stack, depend on `agent-os-kernel` and call into
`prompt_injection.py`.

---

## Other agent-os primitives we don't have

These aren't in the LangChain notebook but are in the same
ecosystem and worth a shopping-list mention:

| Module (`agent_os/...`) | One-line purpose |
|---|---|
| `audit_logger.py` | Pluggable audit backends (JSONL, in-memory, logging) with `AuditEntry` dataclass |
| `circuit_breaker.py` | CLOSED→OPEN→HALF_OPEN state machine for cascading-failure protection |
| `content_governance.py` | Quality gates on agent outputs (accuracy / completeness / freshness / structure / relevance / consistency) |
| `context_budget.py` | Token-budget enforcement; SIGSTOP when lookup or reasoning budget exceeded |
| `credential_redactor.py` | Regex-based detection + redaction of API keys, tokens, passwords in logs |
| `egress_policy.py` | Domain / port / protocol allowlist for outbound network calls |
| `escalation.py` | Escalates governance decisions to humans when confidence is low |
| `event_bus.py` | In-process pub/sub for governance events |
| `execution_context_policy.py` | Per-context enforcement levels (`block`/`warn`/`audit`/`skip`) for inner-loop / CI / autonomous modes |
| `mcp_auth_enforcement.py` | Validates MCP server connections use approved auth (oauth2, mtls, api_key, bearer) |
| `mcp_security.py` | MCP gateway: signature verification, replay detection, nonce tracking |
| `memory_guard.py` | Prevents unbounded memory allocation; enforces heap/buffer limits |
| `policies/backends.py` | Delegate evaluation to external engines (Cedar, OPA, generic HTTP) |
| `policies/conflict_resolution.py` | Multi-policy conflict resolution strategies |
| `policies/data_classification.py` | Data sensitivity levels (PII, confidential, public) |
| `policies/decision_factory.py` | Manufactures policy decisions from YAML/JSON rules |

`agent_os/policies/` alone has 15 submodules; the toolkit is broad.

---

## What we should actually do

Three reasonable strategies, in order of how aggressively we change
`policy-engine`'s scope.

### A. Don't reimplement — point users at the existing bridge

`policy-engine` already ships `policy_engine.adapters.agent_os`,
which delegates to `agent_os_kernel`'s `PolicyInterceptor`
([[Agent-OS-Backend-Adapter]]). For the LangChain notebook
specifically, the cleanest answer is "use `langchain-agentmesh`
directly — it's what the notebook was written for." If you want
policy-engine in the picture, use the adapter, which gives you the
agent-os feature surface while keeping our kernel API in your code.

**Cost:** zero. **Loss:** the LangChain notebook still depends on
agentmesh-specific imports; we don't gain anything reusable.

### B. Port the small, self-contained primitives

Three things from agent-os are short, useful, and don't drag in
heavy deps:

1. **`TokenBucket` rate limiter** — ~50 lines, `time.monotonic` +
   `threading.Lock`. Lives at
   `agent_os/policies/rate_limiting.py`. Land it as
   `policy_engine.rate_limit` and add a `rate_limit:
   RateLimitConfig | None` field to `GovernancePolicy`. New decision
   reason: `rate_limited`.
2. **Regex-based pattern matcher** — replace the substring matcher
   with `re.search`, keep the existing field name. ~10 lines.
   Doesn't hurt the substring case (a literal string is a valid
   regex), but unblocks `\bssn\b`-style patterns the deep-dive
   notebook had to translate.
3. **`payload_summary` opt-in on audit** — *optionally* include the
   first N chars of the payload alongside `payload_hash`, gated by
   an explicit `audit_payload_summary: int = 0` field. Default off
   (preserves current privacy posture). Useful when you want to
   match agentmesh's audit dashboards.

**Cost:** ~150 lines + tests across three small PRs. **Gain:** the
notebook's rate-limiting cell works on top of our engine; pattern
matching is no longer a footgun in the deep-dive tutorial; audit is
optionally agentmesh-compatible.

### C. Build the full identity / trust / capability stack

Port `VerificationIdentity`, `TrustedAgentCard`, `TrustGatedTool`,
`TrustedToolExecutor`, the verification cache, the handshake state
machine. This is the path that makes `04_langchain_agentmesh_chatbot.ipynb`
runnable on a future `policy-engine`.

**Cost:** substantial. ~1000+ lines, plus a new `cryptography`
dependency (optional extra), plus the hard parts: key management,
DID format decisions, scope-chain semantics, replay-window tuning.
Most of this exists already in `langchain-agentmesh` — building it
again would be a rewrite for not-clearly-better reasons.

**Gain:** parity with the agentmesh notebook. **Loss:** we stop
being "the small stdlib-only kernel." The repo's identity changes.

### Recommendation

Do **A + B**. Adopt the rate-limit + regex + opt-in payload-summary
quality-of-life improvements (they're cheap and obviously useful).
For the identity / trust / capability stack, point users at the
existing `agent_os` adapter and at `langchain-agentmesh` directly
rather than rebuilding.

This keeps `policy-engine` honest about what it is — a small,
universal governance kernel that adapters plug into — while making
the cross-ecosystem story coherent.

## Status — what's already landed

Strategy **B** is implemented in this repo. The core is still
stdlib-only and the legacy field shapes are untouched:

```python
# policy_engine.GovernancePolicy now exposes three new optional fields
GovernancePolicy(
    name="example",
    blocked_patterns=[r"\bssn\b", r"DROP\s+TABLE"],
    pattern_engine="regex",                                 # default "substring"
    rate_limit=RateLimitConfig(capacity=5, refill_rate=1.0),# default None
    audit_payload_summary=120,                              # default 0 (off)
)
```

- `policy_engine.rate_limit.TokenBucket` — thread-safe refilling
  bucket; algorithm matches `agent_os.policies.rate_limiting`
  field-for-field. Lives in `ExecutionContext.rate_bucket`,
  instantiated by `BaseKernel.create_context` when the policy
  carries a config. Spent only on calls that *would otherwise be
  allowed* (denied calls don't burn quota). New decision reason:
  `rate_limited:wait_<seconds>s`.
- `pattern_engine="regex"` — opts the matcher into
  `re.search(pattern, text, flags=re.IGNORECASE)`. Substring
  remains the default; existing demos are unaffected.
- `audit_payload_summary` — caller-controlled length hint; if a
  caller passes `audit(..., payload_summary="...")` the entry
  gains a `payload_summary` key alongside `payload_hash`. Default
  `0` keeps the privacy posture untouched (only the hash crosses
  the audit boundary).

Strategy **A** is a no-op: `policy_engine.adapters.agent_os`
already lazy-loads `agent-os-kernel` via the
`policy-engine[agent-os]` extra. No new dependency.

Strategy **C** (identity / cards / trust handshake) is **not**
implemented and is unlikely to be — use `langchain-agentmesh`
directly if you need that surface.

## See also

- [[Core-Concepts]] — what `BaseKernel.evaluate` actually does
- [[Demos]] — every demo currently in the repo and what it exercises
- [[Agent-OS-Backend-Adapter]] — the existing bridge to `agent_os_kernel`
- [[Adapter-API-Shape]] — why each SDK gets a different noun
- [[Naming-Conventions]] — `governed_<noun>` vs `as_<noun>`
