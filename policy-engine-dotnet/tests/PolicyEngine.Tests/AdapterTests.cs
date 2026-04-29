using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;
using PolicyEngine.Adapters.MicrosoftAgents;
using PolicyEngine.Adapters.OpenAI;

namespace PolicyEngine.Tests;

public sealed class AdapterTests
{
    [Fact]
    public async Task MicrosoftAgentsFunctionMiddlewareBlocksDeniedTool()
    {
        MicrosoftAgentsGovernanceMiddleware middleware = new(
            new GovernancePolicy(blockedTools: ["shell_exec"]));
        Func<
            AIAgent,
            FunctionInvocationContext,
            Func<FunctionInvocationContext, CancellationToken, ValueTask<object?>>,
            CancellationToken,
            ValueTask<object?>> gate = middleware.CreateFunctionMiddleware();

        bool nextCalled = false;
        FunctionInvocationContext invocation = new()
        {
            Function = AIFunctionFactory.Create((Func<string>)(() => "ok"), name: "shell_exec"),
        };

        PolicyViolationException exception = await Assert.ThrowsAsync<PolicyViolationException>(async () =>
            await gate(
                null!,
                invocation,
                (_, _) =>
                {
                    nextCalled = true;
                    return new ValueTask<object?>("ok");
                },
                CancellationToken.None));

        Assert.Equal("blocked_tool:shell_exec", exception.Reason);
        Assert.False(nextCalled);
    }

    [Fact]
    public async Task OpenAIAssistantWrapperBlocksBeforeDelegating()
    {
        FakeAssistantOperations operations = new();
        GovernedAssistant assistant = new OpenAIKernel(
            new GovernancePolicy(blockedPatterns: ["DROP TABLE"]))
            .Wrap(operations);

        PolicyViolationException exception = await Assert.ThrowsAsync<PolicyViolationException>(async () =>
            await assistant.AddMessageAsync("thread_1", "DROP TABLE users"));

        Assert.Equal("blocked_pattern:DROP TABLE", exception.Reason);
        Assert.Equal(0, operations.AddMessageCalls);
    }

    [Fact]
    public async Task OpenAIAssistantWrapperDelegatesAllowedMessage()
    {
        FakeAssistantOperations operations = new();
        GovernedAssistant assistant = new OpenAIKernel(
            new GovernancePolicy(blockedPatterns: ["DROP TABLE"]))
            .Wrap(operations);

        object? result = await assistant.AddMessageAsync("thread_1", "Say hello.");

        Assert.Equal("message-created", result);
        Assert.Equal(1, operations.AddMessageCalls);
        Assert.Equal("Say hello.", operations.LastContent);
    }

    private sealed class FakeAssistantOperations : IAssistantOperations
    {
        public string AssistantId => "asst_test";

        public int AddMessageCalls { get; private set; }

        public string? LastContent { get; private set; }

        public ValueTask<object?> CreateThreadAsync(CancellationToken cancellationToken = default) =>
            new("thread-created");

        public ValueTask<object?> AddMessageAsync(
            string threadId,
            string content,
            string role = "user",
            CancellationToken cancellationToken = default)
        {
            AddMessageCalls++;
            LastContent = content;
            return new ValueTask<object?>("message-created");
        }

        public ValueTask<object?> RunAsync(string threadId, CancellationToken cancellationToken = default) =>
            new("run-created");

        public ValueTask<object?> ListMessagesAsync(
            string threadId,
            string order = "desc",
            int limit = 1,
            CancellationToken cancellationToken = default) =>
            new("messages-listed");

        public ValueTask<object?> DeleteThreadAsync(string threadId, CancellationToken cancellationToken = default) =>
            new("thread-deleted");
    }
}
