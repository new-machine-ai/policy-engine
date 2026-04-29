# .NET 10 Port

The repository includes an additive .NET 10 C# port under
`policy-engine-dotnet/`. It preserves the Python core behavior while leaving the
Python package and demos intact.

## What Is Included

- `PolicyEngine`: dependency-free core with `GovernancePolicy`,
  `PolicyRequest`, `PolicyDecision`, `PolicyViolationException`,
  `ExecutionContext`, `BaseKernel`, and `PolicyAudit`.
- `PolicyEngine.Adapters.MicrosoftAgents`: Microsoft Agent Framework
  agent-run, function, and `IChatClient` middleware.
- `PolicyEngine.Adapters.OpenAI`: OpenAI Assistants facade and
  `Microsoft.Extensions.AI` `IChatClient` middleware.
- `PolicyEngine.Demos`: offline console demos for `core`, `maf`, `openai`, and
  `run-all`.
- `PolicyEngine.Tests`: xUnit parity tests for the Python core behavior plus
  adapter delegation/blocking tests.

Agent-OS is intentionally excluded from the .NET port. The Python
`policy_engine.adapters.agent_os` bridge remains the only Agent-OS integration
in this checkout.

## Commands

```bash
dotnet build policy-engine-dotnet/PolicyEngine.sln
dotnet test policy-engine-dotnet/PolicyEngine.sln
dotnet run --project policy-engine-dotnet/samples/PolicyEngine.Demos -- run-all
```

The .NET core preserves the same check order and reason strings as Python:

1. max-tool-call cap
2. blocked tool
3. allowlist miss
4. human approval required
5. blocked prompt pattern
6. allowed decision and call-count increment

Audit records store metadata and `payload_hash`; raw prompts are not persisted.
