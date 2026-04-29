namespace PolicyEngine.Adapters.MicrosoftAgents;

public sealed class MicrosoftAgentsKernel : BaseKernel
{
    public MicrosoftAgentsKernel(GovernancePolicy policy)
        : base(policy)
    {
    }

    public override string Framework => "microsoft_agents";
}
