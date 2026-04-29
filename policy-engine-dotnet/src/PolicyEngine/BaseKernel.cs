namespace PolicyEngine;

public class BaseKernel
{
    public BaseKernel(GovernancePolicy policy)
    {
        policy.Validate();
        Policy = policy;
    }

    public virtual string Framework => "base";

    public GovernancePolicy Policy { get; }

    public ExecutionContext CreateContext(string name) => new(name, Policy);

    public virtual PolicyDecision Evaluate(ExecutionContext context, string payload) =>
        Evaluate(context, new PolicyRequest(Payload: payload));

    public virtual PolicyDecision Evaluate(ExecutionContext context, PolicyRequest request)
    {
        ArgumentNullException.ThrowIfNull(context);
        ArgumentNullException.ThrowIfNull(request);

        string payloadHash = request.PayloadSha256();

        PolicyDecision Decision(
            bool allowed,
            string? reason = null,
            string? matchedPattern = null,
            bool requiresApproval = false) =>
            new(
                Allowed: allowed,
                Reason: reason,
                Policy: Policy.Name,
                MatchedPattern: matchedPattern,
                ToolName: request.ToolName,
                RequiresApproval: requiresApproval,
                PayloadHash: payloadHash,
                Phase: request.Phase);

        if (context.CallCount >= Policy.MaxToolCalls)
        {
            return Decision(false, "max_tool_calls exceeded");
        }

        if (request.ToolName is not null)
        {
            if (Policy.BlockedTools is not null && Policy.BlockedTools.Contains(request.ToolName))
            {
                return Decision(false, $"blocked_tool:{request.ToolName}");
            }

            if (Policy.AllowedTools is not null && !Policy.AllowedTools.Contains(request.ToolName))
            {
                return Decision(false, $"tool_not_allowed:{request.ToolName}");
            }
        }

        if (Policy.RequireHumanApproval)
        {
            return Decision(false, "human_approval_required", requiresApproval: true);
        }

        string? matched = Policy.MatchesPattern(request.Payload);
        if (matched is not null)
        {
            return Decision(false, $"blocked_pattern:{matched}", matchedPattern: matched);
        }

        context.CallCount++;
        return Decision(true);
    }

    public (bool Allowed, string? Reason) PreExecute(ExecutionContext context, string payload)
    {
        PolicyDecision decision = Evaluate(context, new PolicyRequest(Payload: payload));
        return (decision.Allowed, decision.Reason);
    }
}
