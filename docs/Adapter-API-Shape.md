# Adapter API Shape

Every adapter exposes the smallest object its host SDK can actually accept.

| Shape | Meaning | Examples |
|---|---|---|
| `governed_<noun>(seed)` | Return a policy-gated copy or wrapper around an SDK object the caller already created. | `AnthropicKernel.governed_client(client)`, `ClaudeSDKKernel.governed_options(options)`, `OpenAIAgentsKernel.governed_runner(Runner)` |
| `as_<noun>()` | Construct a fresh SDK hook/middleware/plugin handle from the kernel policy. | `LangChainKernel.as_middleware()`, `MAFKernel.as_middleware()`, `GoogleADKKernel.as_callbacks()`, `GoogleADKKernel.as_plugin()` |

Google ADK uses the second shape twice because ADK has two native seams:

- `as_callbacks()` returns `before_tool_callback` and `after_tool_callback` for
  `LlmAgent(..., **callbacks)`.
- `as_plugin()` returns a Runner plugin for `Runner(..., plugins=[...])` and can
  also gate model requests before they leave ADK.

The demo split follows those seams: the callback demo is deterministic and
directly calls the ADK-shaped callbacks; the hello-world sample is live and runs
through an ADK `LlmAgent` plus `InMemoryRunner`.
