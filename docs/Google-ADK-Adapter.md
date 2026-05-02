# Google ADK

**Source:** `policy-engine/src/policy_engine/adapters/google_adk.py`
**Deterministic demo:** `policy_engine_demos/google_adk_callbacks_governed.py`
**Live demo:** `policy_engine_hello_world_multi_real/google_adk_agent.py`

## Seam

Google ADK exposes both agent-level callbacks and runner-scoped plugins. The
adapter supports both:

```python
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from policy_engine import GovernancePolicy
from policy_engine.adapters.google_adk import GoogleADKKernel

kernel = GoogleADKKernel(
    GovernancePolicy(
        blocked_patterns=["DROP TABLE", "rm -rf"],
        allowed_tools=["search", "summarize"],
        blocked_tools=["shell"],
    )
)

agent = LlmAgent(
    name="assistant",
    model="gemini-2.5-flash",
    **kernel.as_callbacks(),
)
runner = InMemoryRunner(agent=agent, plugins=[kernel.as_plugin()])
```

## Behavior

- `before_tool_callback` evaluates tool name and serialized arguments before a
  tool runs.
- `after_tool_callback` evaluates serialized tool output after a tool returns.
- `as_plugin()` also evaluates model input before ADK sends the request.
- Blocks return ADK's native callback short-circuit shape, `{"error": ...}`.
- Audit entries include policy metadata, tool name, reason, and payload hash,
  never raw prompts, tool arguments, or tool output.

`max_budget` is adapter-local compatibility surface for Agent-OS style examples.
It is not added to `GovernancePolicy`.
