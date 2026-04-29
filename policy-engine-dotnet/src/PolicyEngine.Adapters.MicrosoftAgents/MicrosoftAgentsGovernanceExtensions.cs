using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;

namespace PolicyEngine.Adapters.MicrosoftAgents;

public static class MicrosoftAgentsGovernanceExtensions
{
    public static AIAgentBuilder UsePolicyEngine(
        this AIAgentBuilder builder,
        GovernancePolicy policy,
        string contextName = "microsoft-agents",
        bool includeFunctionMiddleware = true)
    {
        ArgumentNullException.ThrowIfNull(builder);
        MicrosoftAgentsGovernanceMiddleware middleware = new(policy, contextName);

        builder.Use(middleware.CreateAgentRunMiddleware());
        if (includeFunctionMiddleware)
        {
            builder.Use(middleware.CreateFunctionMiddleware());
        }

        return builder;
    }

    public static ChatClientBuilder UsePolicyEngine(
        this ChatClientBuilder builder,
        GovernancePolicy policy,
        string contextName = "microsoft-agents-chat")
    {
        ArgumentNullException.ThrowIfNull(builder);
        MicrosoftAgentsGovernanceMiddleware middleware = new(policy, contextName);
        return builder.Use(
            getResponseFunc: middleware.CreateChatMiddleware(),
            getStreamingResponseFunc: middleware.CreateStreamingChatMiddleware());
    }
}
