namespace PolicyEngine;

public sealed record PolicyDecision(
    bool Allowed,
    string? Reason = null,
    string Policy = "",
    string? MatchedPattern = null,
    string? ToolName = null,
    bool RequiresApproval = false,
    string PayloadHash = "",
    string Phase = "pre_execute");
