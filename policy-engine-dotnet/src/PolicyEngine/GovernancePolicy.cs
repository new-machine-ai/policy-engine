namespace PolicyEngine;

public sealed class GovernancePolicy
{
    public GovernancePolicy(
        string name = "default",
        IEnumerable<string>? blockedPatterns = null,
        int maxToolCalls = 10,
        bool requireHumanApproval = false,
        IEnumerable<string>? allowedTools = null,
        IEnumerable<string>? blockedTools = null)
    {
        Name = name;
        BlockedPatterns = [.. blockedPatterns ?? []];
        MaxToolCalls = maxToolCalls;
        RequireHumanApproval = requireHumanApproval;
        AllowedTools = allowedTools is null ? null : [.. allowedTools];
        BlockedTools = blockedTools is null ? null : [.. blockedTools];
    }

    public string Name { get; }

    public IReadOnlyList<string> BlockedPatterns { get; }

    public int MaxToolCalls { get; }

    public bool RequireHumanApproval { get; }

    public IReadOnlyList<string>? AllowedTools { get; }

    public IReadOnlyList<string>? BlockedTools { get; }

    public void Validate()
    {
        if (MaxToolCalls < 0)
        {
            throw new ArgumentException("max_tool_calls must be >= 0", nameof(MaxToolCalls));
        }

        if (BlockedPatterns.Any(pattern => string.IsNullOrWhiteSpace(pattern)))
        {
            throw new ArgumentException("blocked_patterns must not contain blank entries", nameof(BlockedPatterns));
        }

        if (AllowedTools is not null && BlockedTools is not null)
        {
            string[] overlap = AllowedTools.Intersect(BlockedTools, StringComparer.Ordinal).Order().ToArray();
            if (overlap.Length > 0)
            {
                throw new ArgumentException($"tools cannot be both allowed and blocked: {string.Join(", ", overlap)}");
            }
        }
    }

    public string? MatchesPattern(string? text)
    {
        if (string.IsNullOrEmpty(text))
        {
            return null;
        }

        foreach (string pattern in BlockedPatterns)
        {
            if (text.Contains(pattern, StringComparison.OrdinalIgnoreCase))
            {
                return pattern;
            }
        }

        return null;
    }
}
