# policy-engine-dotnet

.NET 10 C# port of the small runtime policy engine in `../policy-engine`.

This is an additive port. The Python package remains in place as the behavioral
reference, and Agent-OS is intentionally excluded from this .NET solution.

## Layout

| Path | Purpose |
|---|---|
| `src/PolicyEngine` | Dependency-free core policy engine, context, decisions, exception, and audit sink. |
| `src/PolicyEngine.Adapters.MicrosoftAgents` | Microsoft Agent Framework middleware and `IChatClient` pipeline hooks. |
| `src/PolicyEngine.Adapters.OpenAI` | OpenAI Assistants facade and `IChatClient` pipeline hooks. |
| `samples/PolicyEngine.Demos` | Offline console demos for `core`, `maf`, `openai`, and `run-all`. |
| `tests/PolicyEngine.Tests` | xUnit parity tests ported from the Python suite plus adapter tests. |

## Commands

Run from the repository root:

```bash
dotnet restore policy-engine-dotnet/PolicyEngine.sln
dotnet build policy-engine-dotnet/PolicyEngine.sln
dotnet test policy-engine-dotnet/PolicyEngine.sln
dotnet run --project policy-engine-dotnet/samples/PolicyEngine.Demos -- run-all
dotnet run --project policy-engine-dotnet/samples/PolicyEngine.Demos -- --list
```

The demos do not require API keys. They use fake framework operations where a
live OpenAI or MAF agent call would otherwise be needed.

## Core API

```csharp
using PolicyEngine;

var policy = new GovernancePolicy(
    name: "my-policy",
    blockedPatterns: ["DROP TABLE", "rm -rf"],
    maxToolCalls: 10,
    blockedTools: ["shell_exec"]);

var kernel = new BaseKernel(policy);
var context = kernel.CreateContext("run-1");

PolicyDecision decision = kernel.Evaluate(
    context,
    new PolicyRequest(Payload: "Say hello.", ToolName: "search"));

(bool allowed, string? reason) = kernel.PreExecute(context, "Say hello.");
```

## Adapter Scope

The .NET port includes only .NET-native adapter surfaces:

- Microsoft Agent Framework via agent-run, function, and chat middleware.
- OpenAI via an Assistants facade and `Microsoft.Extensions.AI` chat middleware.

The Python-only adapters for LangChain, CrewAI, PydanticAI, Claude Agent SDK,
and the Agent-OS backend bridge are not ported here.
