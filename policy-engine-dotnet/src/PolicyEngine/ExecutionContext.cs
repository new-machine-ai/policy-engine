namespace PolicyEngine;

public sealed class ExecutionContext
{
    public ExecutionContext(string name, GovernancePolicy policy)
    {
        Name = name;
        Policy = policy;
    }

    public string Name { get; }

    public GovernancePolicy Policy { get; }

    public int CallCount { get; set; }
}
