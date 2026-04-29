using System.Security.Cryptography;
using System.Text;

namespace PolicyEngine.Tests;

public sealed class PolicyEngineCoreTests
{
    [Fact]
    public void MatchesPatternHit()
    {
        GovernancePolicy policy = new(blockedPatterns: ["DROP TABLE"]);

        Assert.Equal("DROP TABLE", policy.MatchesPattern("please DROP TABLE users"));
    }

    [Fact]
    public void MatchesPatternCaseInsensitive()
    {
        GovernancePolicy policy = new(blockedPatterns: ["DROP TABLE"]);

        Assert.Equal("DROP TABLE", policy.MatchesPattern("drop table users"));
    }

    [Fact]
    public void MatchesPatternMiss()
    {
        GovernancePolicy policy = new(blockedPatterns: ["DROP TABLE"]);

        Assert.Null(policy.MatchesPattern("hello"));
    }

    [Fact]
    public void MatchesPatternEmptyText()
    {
        GovernancePolicy policy = new(blockedPatterns: ["x"]);

        Assert.Null(policy.MatchesPattern(""));
    }

    [Fact]
    public void PreExecuteAllowsSafeInput()
    {
        (BaseKernel kernel, PolicyEngine.ExecutionContext context) = MakeKernel();

        (bool allowed, string? reason) = kernel.PreExecute(context, "Say hello.");

        Assert.True(allowed);
        Assert.Null(reason);
        Assert.Equal(1, context.CallCount);
    }

    [Fact]
    public void PreExecuteBlocksPattern()
    {
        (BaseKernel kernel, PolicyEngine.ExecutionContext context) = MakeKernel();

        (bool allowed, string? reason) = kernel.PreExecute(context, "DROP TABLE users");

        Assert.False(allowed);
        Assert.Equal("blocked_pattern:DROP TABLE", reason);
        Assert.Equal(0, context.CallCount);
    }

    [Fact]
    public void PreExecuteMaxToolCallsCap()
    {
        (BaseKernel kernel, PolicyEngine.ExecutionContext context) = MakeKernel();

        for (int i = 0; i < 10; i++)
        {
            (bool allowed, _) = kernel.PreExecute(context, "ok");
            Assert.True(allowed);
        }

        (bool blocked, string? reason) = kernel.PreExecute(context, "ok");

        Assert.False(blocked);
        Assert.Equal("max_tool_calls exceeded", reason);
    }

    [Fact]
    public void EvaluateReturnsStructuredDecision()
    {
        (BaseKernel kernel, PolicyEngine.ExecutionContext context) = MakeKernel();

        PolicyDecision decision = kernel.Evaluate(context, new PolicyRequest(Payload: "Say hello."));

        Assert.True(decision.Allowed);
        Assert.Null(decision.Reason);
        Assert.Equal("t", decision.Policy);
        Assert.Equal(Sha256("Say hello."), decision.PayloadHash);
        Assert.Equal(1, context.CallCount);
    }

    [Fact]
    public void PolicyValidationRejectsNegativeMaxToolCalls()
    {
        GovernancePolicy policy = new(maxToolCalls: -1);

        ArgumentException ex = Assert.Throws<ArgumentException>(() => new BaseKernel(policy));
        Assert.Contains("max_tool_calls", ex.Message);
    }

    [Fact]
    public void PolicyValidationRejectsBlankBlockedPattern()
    {
        GovernancePolicy policy = new(blockedPatterns: ["DROP TABLE", " "]);

        ArgumentException ex = Assert.Throws<ArgumentException>(() => new BaseKernel(policy));
        Assert.Contains("blocked_patterns", ex.Message);
    }

    [Fact]
    public void PolicyValidationRejectsOverlappingTools()
    {
        GovernancePolicy policy = new(
            allowedTools: ["search", "shell_exec"],
            blockedTools: ["shell_exec"]);

        ArgumentException ex = Assert.Throws<ArgumentException>(() => new BaseKernel(policy));
        Assert.Contains("both allowed and blocked", ex.Message);
    }

    [Fact]
    public void EvaluateBlocksDeniedTool()
    {
        GovernancePolicy policy = new(name: "tools", blockedTools: ["shell_exec"]);
        BaseKernel kernel = new(policy);
        PolicyEngine.ExecutionContext context = kernel.CreateContext("test");

        PolicyDecision decision = kernel.Evaluate(
            context,
            new PolicyRequest(Payload: "ok", ToolName: "shell_exec"));

        Assert.False(decision.Allowed);
        Assert.Equal("blocked_tool:shell_exec", decision.Reason);
        Assert.Equal("shell_exec", decision.ToolName);
        Assert.Equal(0, context.CallCount);
    }

    [Fact]
    public void EvaluateBlocksToolNotInAllowlist()
    {
        GovernancePolicy policy = new(name: "tools", allowedTools: ["search"]);
        BaseKernel kernel = new(policy);
        PolicyEngine.ExecutionContext context = kernel.CreateContext("test");

        PolicyDecision decision = kernel.Evaluate(
            context,
            new PolicyRequest(Payload: "ok", ToolName: "shell_exec"));

        Assert.False(decision.Allowed);
        Assert.Equal("tool_not_allowed:shell_exec", decision.Reason);
        Assert.Equal(0, context.CallCount);
    }

    [Fact]
    public void EvaluateRequiresHumanApproval()
    {
        GovernancePolicy policy = new(name: "approval", requireHumanApproval: true);
        BaseKernel kernel = new(policy);
        PolicyEngine.ExecutionContext context = kernel.CreateContext("test");

        PolicyDecision decision = kernel.Evaluate(context, new PolicyRequest(Payload: "ok"));

        Assert.False(decision.Allowed);
        Assert.Equal("human_approval_required", decision.Reason);
        Assert.True(decision.RequiresApproval);
        Assert.Equal(0, context.CallCount);
    }

    [Fact]
    public void MaxCallsCheckedBeforePatterns()
    {
        GovernancePolicy policy = new(blockedPatterns: ["DROP TABLE"], maxToolCalls: 0);
        BaseKernel kernel = new(policy);
        PolicyEngine.ExecutionContext context = kernel.CreateContext("test");

        PolicyDecision decision = kernel.Evaluate(context, new PolicyRequest(Payload: "DROP TABLE users"));

        Assert.False(decision.Allowed);
        Assert.Equal("max_tool_calls exceeded", decision.Reason);
        Assert.Null(decision.MatchedPattern);
    }

    [Fact]
    public void AuditRecordsStructuredDecisionWithoutRawPayload()
    {
        PolicyAudit.Reset();
        (BaseKernel kernel, PolicyEngine.ExecutionContext context) = MakeKernel();
        PolicyDecision decision = kernel.Evaluate(context, new PolicyRequest(Payload: "Say hello."));

        AuditRecord record = PolicyAudit.Audit("test", "pre_execute", "ALLOWED", decision: decision);
        IReadOnlyDictionary<string, string> dictionary = record.ToDictionary();

        Assert.Equal("t", dictionary["policy"]);
        Assert.Equal(Sha256("Say hello."), dictionary["payload_hash"]);
        Assert.False(dictionary.ContainsKey("payload"));
        Assert.EndsWith("+00:00", dictionary["ts"]);
        PolicyAudit.Reset();
    }

    [Fact]
    public void PolicyViolationExceptionCarriesReason()
    {
        PolicyViolationException exception = new("blocked", pattern: "DROP TABLE");

        Assert.Equal("blocked", exception.Reason);
        Assert.Equal("DROP TABLE", exception.Pattern);
        Assert.Equal("blocked", exception.Message);
    }

    private static (BaseKernel Kernel, PolicyEngine.ExecutionContext Context) MakeKernel()
    {
        GovernancePolicy policy = new(
            name: "t",
            blockedPatterns: ["DROP TABLE", "rm -rf"],
            maxToolCalls: 10);
        BaseKernel kernel = new(policy);
        return (kernel, kernel.CreateContext("test"));
    }

    private static string Sha256(string value) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();
}
