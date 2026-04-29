using System.Runtime.CompilerServices;
using Microsoft.Extensions.AI;

namespace PolicyEngine.Adapters.OpenAI;

public static class OpenAIChatClientGovernanceExtensions
{
    public static ChatClientBuilder UsePolicyEngine(
        this ChatClientBuilder builder,
        GovernancePolicy policy,
        string contextName = "openai-chat")
    {
        ArgumentNullException.ThrowIfNull(builder);

        OpenAIKernel kernel = new(policy);
        PolicyEngine.ExecutionContext context = kernel.CreateContext(contextName);

        return builder.Use(
            getResponseFunc: async (messages, options, innerClient, cancellationToken) =>
            {
                Gate(kernel, context, messages, "chat");
                return await innerClient.GetResponseAsync(messages, options, cancellationToken).ConfigureAwait(false);
            },
            getStreamingResponseFunc: (messages, options, innerClient, cancellationToken) =>
                Stream(kernel, context, messages, options, innerClient, cancellationToken));
    }

    public static PolicyDecision EvaluateChat(
        GovernancePolicy policy,
        IEnumerable<ChatMessage> messages,
        string contextName = "openai-chat")
    {
        OpenAIKernel kernel = new(policy);
        return kernel.Evaluate(
            kernel.CreateContext(contextName),
            new PolicyRequest(Payload: ExtractPayload(messages), Phase: "chat"));
    }

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

    private static void Gate(
        OpenAIKernel kernel,
        PolicyEngine.ExecutionContext context,
        IEnumerable<ChatMessage> messages,
        string phase)
    {
        PolicyDecision decision = kernel.Evaluate(
            context,
            new PolicyRequest(Payload: ExtractPayload(messages), Phase: phase));

        if (!decision.Allowed)
        {
            PolicyAudit.Audit("openai", phase, "BLOCKED", decision.Reason ?? "blocked", decision);
            throw new PolicyViolationException(decision.Reason ?? "blocked", decision.MatchedPattern);
        }

        PolicyAudit.Audit("openai", phase, "ALLOWED", decision: decision);
    }

    private static async IAsyncEnumerable<ChatResponseUpdate> Stream(
        OpenAIKernel kernel,
        PolicyEngine.ExecutionContext context,
        IEnumerable<ChatMessage> messages,
        ChatOptions? options,
        IChatClient innerClient,
        [EnumeratorCancellation] CancellationToken cancellationToken)
    {
        Gate(kernel, context, messages, "chat");
        await foreach (ChatResponseUpdate update in innerClient
            .GetStreamingResponseAsync(messages, options, cancellationToken)
            .WithCancellation(cancellationToken)
            .ConfigureAwait(false))
        {
            yield return update;
        }
    }
}
