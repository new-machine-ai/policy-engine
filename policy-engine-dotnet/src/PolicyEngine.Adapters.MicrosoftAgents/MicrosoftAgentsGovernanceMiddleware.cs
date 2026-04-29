using System.Runtime.CompilerServices;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;

namespace PolicyEngine.Adapters.MicrosoftAgents;

public sealed class MicrosoftAgentsGovernanceMiddleware
{
    private readonly MicrosoftAgentsKernel _kernel;
    private readonly PolicyEngine.ExecutionContext _context;

    public MicrosoftAgentsGovernanceMiddleware(
        GovernancePolicy policy,
        string contextName = "microsoft-agents")
    {
        _kernel = new MicrosoftAgentsKernel(policy);
        _context = _kernel.CreateContext(contextName);
    }

    public Func<
        IEnumerable<ChatMessage>,
        AgentSession?,
        AgentRunOptions?,
        Func<IEnumerable<ChatMessage>, AgentSession?, AgentRunOptions?, CancellationToken, Task>,
        CancellationToken,
        Task> CreateAgentRunMiddleware() =>
        async (messages, session, options, next, cancellationToken) =>
        {
            PolicyDecision decision = _kernel.Evaluate(
                _context,
                new PolicyRequest(Payload: ExtractPayload(messages), Phase: "agent_run"));

            if (!decision.Allowed)
            {
                PolicyAudit.Audit(
                    "microsoft_agents",
                    "agent_run",
                    "BLOCKED",
                    decision.Reason ?? "blocked",
                    decision);
                throw new PolicyViolationException(decision.Reason ?? "blocked", decision.MatchedPattern);
            }

            PolicyAudit.Audit("microsoft_agents", "agent_run", "ALLOWED", decision: decision);
            await next(messages, session, options, cancellationToken).ConfigureAwait(false);
        };

    public Func<
        AIAgent,
        FunctionInvocationContext,
        Func<FunctionInvocationContext, CancellationToken, ValueTask<object?>>,
        CancellationToken,
        ValueTask<object?>> CreateFunctionMiddleware() =>
        async (agent, invocation, next, cancellationToken) =>
        {
            string? toolName = invocation.Function?.Name;
            string payload = ExtractPayload(invocation.Messages);
            if (invocation.Arguments.Count > 0)
            {
                payload = string.Join(
                    " ",
                    new[] { payload }.Concat(invocation.Arguments.Values.Select(value => value?.ToString() ?? string.Empty)));
            }

            PolicyDecision decision = _kernel.Evaluate(
                _context,
                new PolicyRequest(
                    Payload: payload,
                    ToolName: toolName,
                    Phase: toolName is null ? "function_call" : "tool_call"));

            if (!decision.Allowed)
            {
                PolicyAudit.Audit(
                    "microsoft_agents",
                    "function_call",
                    "BLOCKED",
                    decision.Reason ?? "blocked",
                    decision);
                throw new PolicyViolationException(decision.Reason ?? "blocked", decision.MatchedPattern);
            }

            PolicyAudit.Audit(
                "microsoft_agents",
                "function_call",
                "ALLOWED",
                toolName ?? string.Empty,
                decision);
            return await next(invocation, cancellationToken).ConfigureAwait(false);
        };

    public Func<
        IEnumerable<ChatMessage>,
        ChatOptions?,
        IChatClient,
        CancellationToken,
        Task<ChatResponse>> CreateChatMiddleware() =>
        async (messages, options, innerClient, cancellationToken) =>
        {
            GateChat(messages);
            return await innerClient.GetResponseAsync(messages, options, cancellationToken).ConfigureAwait(false);
        };

    public Func<
        IEnumerable<ChatMessage>,
        ChatOptions?,
        IChatClient,
        CancellationToken,
        IAsyncEnumerable<ChatResponseUpdate>> CreateStreamingChatMiddleware() =>
        (messages, options, innerClient, cancellationToken) => Stream(messages, options, innerClient, cancellationToken);

    public PolicyDecision EvaluateChat(IEnumerable<ChatMessage> messages) =>
        _kernel.Evaluate(
            _context,
            new PolicyRequest(Payload: ExtractPayload(messages), Phase: "chat"));

    public PolicyDecision EvaluateFunction(string? toolName, string? payload = null) =>
        _kernel.Evaluate(
            _context,
            new PolicyRequest(Payload: payload ?? string.Empty, ToolName: toolName, Phase: "tool_call"));

    public static string ExtractPayload(IEnumerable<ChatMessage>? messages)
    {
        if (messages is null)
        {
            return string.Empty;
        }

        string[] textParts = messages
            .SelectMany(message => message.Contents)
            .OfType<TextContent>()
            .Select(content => content.Text)
            .Where(text => !string.IsNullOrEmpty(text))
            .ToArray();

        return textParts.Length == 0 ? string.Empty : string.Join(" ", textParts);
    }

    private void GateChat(IEnumerable<ChatMessage> messages)
    {
        PolicyDecision decision = EvaluateChat(messages);
        if (!decision.Allowed)
        {
            PolicyAudit.Audit(
                "microsoft_agents",
                "chat",
                "BLOCKED",
                decision.Reason ?? "blocked",
                decision);
            throw new PolicyViolationException(decision.Reason ?? "blocked", decision.MatchedPattern);
        }

        PolicyAudit.Audit("microsoft_agents", "chat", "ALLOWED", decision: decision);
    }

    private async IAsyncEnumerable<ChatResponseUpdate> Stream(
        IEnumerable<ChatMessage> messages,
        ChatOptions? options,
        IChatClient innerClient,
        [EnumeratorCancellation] CancellationToken cancellationToken)
    {
        GateChat(messages);
        await foreach (ChatResponseUpdate update in innerClient
            .GetStreamingResponseAsync(messages, options, cancellationToken)
            .WithCancellation(cancellationToken)
            .ConfigureAwait(false))
        {
            yield return update;
        }
    }
}
