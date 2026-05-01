# Seam Taxonomy

| Framework | Pattern | Where the adapter calls `evaluate` / `pre_execute` | Other hook points the adapter does **not** use |
|---|---|---|---|
| [[MAF-Adapter]] | Middleware factory | Inside `_policy_gate(context, next_)` before `await next_(context)` | function-level middleware |
| [[OpenAI-Assistants-Adapter]] | Method proxy | `GovernedAssistant.add_message(...)` only | streaming step events, `submit_tool_outputs` interception |
| [[OpenAI-Agents-SDK-Adapter]] | Method proxy + native hooks | `GovernedRunner.run(...)` (demo subclasses `RunHooks`) | `Guardrail` (input/output), `on_tool_*`, `on_handoff` |
| [[LangChain-Adapter]] | Bare kernel | Demo's `gov_pre_model` `pre_model_hook` | `post_model_hook`, full `BaseCallbackHandler` surface, `interrupt_before/after` |
| [[CrewAI-Adapter]] | Bare kernel | Demo's `@before_llm_call` / `@after_llm_call` | `@before_kickoff`/`@after_kickoff`, `step_callback`, per-tool decorators |
| [[PydanticAI-Adapter]] | Method proxy | `_GovernedPydanticAgent.run(...)` | `@output_validator`, `UsageLimits`, `run_sync` / `run_stream` |
| [[Claude-Agent-SDK-Adapter]] | Hook factory | `gov_hook` registered on `UserPromptSubmit` | `PreToolUse`, `PostToolUse`, `SessionStart`, `Stop`, etc. |
| [[Anthropic-Adapter]] | Message hook | `GovernanceMessageHook.create(client, ...)` before `client.messages.create(...)` | streaming, beta APIs, client proxy wrapping |
| [[Agent-OS-Backend-Adapter]] | Backend bridge (BaseKernel subclass) | Override of `evaluate` delegating to `PolicyInterceptor.intercept` | n/a — backend, not a host framework |
