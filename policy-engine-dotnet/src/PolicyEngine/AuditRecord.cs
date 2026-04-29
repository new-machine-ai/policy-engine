using System.Globalization;

namespace PolicyEngine;

public sealed record AuditRecord(
    DateTimeOffset Timestamp,
    string Framework,
    string Phase,
    string Status,
    string Detail,
    string? Policy = null,
    string? Reason = null,
    string? ToolName = null,
    string? PayloadHash = null)
{
    public string TimestampIso => Timestamp.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:sszzz", CultureInfo.InvariantCulture);

    public IReadOnlyDictionary<string, string> ToDictionary()
    {
        Dictionary<string, string> record = new(StringComparer.Ordinal)
        {
            ["ts"] = TimestampIso,
            ["framework"] = Framework,
            ["phase"] = Phase,
            ["status"] = Status,
            ["detail"] = Detail,
        };

        if (!string.IsNullOrEmpty(Policy))
        {
            record["policy"] = Policy;
        }

        if (!string.IsNullOrEmpty(Reason))
        {
            record["reason"] = Reason;
        }

        if (!string.IsNullOrEmpty(ToolName))
        {
            record["tool_name"] = ToolName;
        }

        if (!string.IsNullOrEmpty(PayloadHash))
        {
            record["payload_hash"] = PayloadHash;
        }

        return record;
    }
}
