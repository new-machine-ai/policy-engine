# Anthropic SDK

**Source:** `policy-engine/src/policy_engine/adapters/anthropic.py`  
**Demo:** `policy_engine_hello_world_multi_real_consolidated/anthropic_agent.py`

## Seam

The Anthropic Python SDK does not expose a first-class middleware interface for
`client.messages.create(...)`. The adapter therefore provides an explicit
message hook:

```python
from anthropic import Anthropic
from policy_engine import GovernancePolicy
from policy_engine.adapters.anthropic import AnthropicKernel

kernel = AnthropicKernel(
    GovernancePolicy(blocked_patterns=["password", "api_key"])
)
hook = kernel.as_message_hook(name="hello-world-anthropic")
response = hook.create(
    Anthropic(),
    model="claude-sonnet-4-5-20250929",
    max_tokens=128,
    messages=[{"role": "user", "content": "Say hello in 5 words"}],
)
```

## Behavior

- Each inbound message content block is evaluated before delegation.
- Requested tool definitions are evaluated with `tool_name` when present.
- Returned `tool_use` blocks are also evaluated against tool policy.
- Blocks raise `PolicyViolationError`.
- Audit entries include policy metadata and payload hashes, never raw prompts.

The adapter intentionally does not add token-budget fields to
`GovernancePolicy`; Anthropic `max_tokens` remains part of the SDK request.
