namespace PolicyEngine;

public static class PolicyAudit
{
    private static readonly object SyncRoot = new();
    private static readonly List<AuditRecord> RecordsCore = [];

    public static IReadOnlyList<AuditRecord> Records
    {
        get
        {
            lock (SyncRoot)
            {
                return RecordsCore.ToArray();
            }
        }
    }

    public static AuditRecord Audit(
        string framework,
        string phase,
        string status,
        string detail = "",
        PolicyDecision? decision = null,
        string? policy = null,
        string? reason = null,
        string? toolName = null,
        string? payloadHash = null)
    {
        if (decision is not null)
        {
            policy ??= decision.Policy;
            reason ??= decision.Reason;
            toolName ??= decision.ToolName;
            payloadHash ??= decision.PayloadHash;
        }

        AuditRecord record = new(
            Timestamp: DateTimeOffset.UtcNow,
            Framework: framework,
            Phase: phase,
            Status: status,
            Detail: detail,
            Policy: policy,
            Reason: reason,
            ToolName: toolName,
            PayloadHash: payloadHash);

        lock (SyncRoot)
        {
            RecordsCore.Add(record);
        }

        Console.WriteLine($"gov[{framework}:{phase}] {status}{(string.IsNullOrEmpty(detail) ? string.Empty : $" - {detail}")}");
        return record;
    }

    public static void Reset()
    {
        lock (SyncRoot)
        {
            RecordsCore.Clear();
        }
    }
}
