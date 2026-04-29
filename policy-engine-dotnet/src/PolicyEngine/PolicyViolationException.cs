namespace PolicyEngine;

public sealed class PolicyViolationException : Exception
{
    public PolicyViolationException(string reason, string? pattern = null)
        : base(reason)
    {
        Reason = reason;
        Pattern = pattern;
    }

    public string Reason { get; }

    public string? Pattern { get; }
}
