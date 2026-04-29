using System.Security.Cryptography;
using System.Text;

namespace PolicyEngine;

public sealed record PolicyRequest(
    string? Payload = "",
    string? ToolName = null,
    string Phase = "pre_execute")
{
    public string PayloadSha256()
    {
        byte[] bytes = Encoding.UTF8.GetBytes(Payload ?? string.Empty);
        byte[] hash = SHA256.HashData(bytes);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }
}
