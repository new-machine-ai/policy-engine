namespace PolicyEngine.Adapters.OpenAI;

public sealed class GovernedAssistant
{
    private readonly OpenAIKernel _kernel;
    private readonly IAssistantOperations _operations;
    private readonly PolicyEngine.ExecutionContext _context;

    internal GovernedAssistant(OpenAIKernel kernel, IAssistantOperations operations)
    {
        _kernel = kernel;
        _operations = operations;
        _context = kernel.CreateContext($"assistant:{operations.AssistantId}");
    }

    public string Id => _operations.AssistantId;

    public ValueTask<object?> CreateThreadAsync(CancellationToken cancellationToken = default) =>
        _operations.CreateThreadAsync(cancellationToken);

    public async ValueTask<object?> AddMessageAsync(
        string threadId,
        string content,
        string role = "user",
        CancellationToken cancellationToken = default)
    {
        PolicyDecision decision = _kernel.Evaluate(
            _context,
            new PolicyRequest(Payload: content, Phase: "add_message"));

        if (!decision.Allowed)
        {
            PolicyAudit.Audit("openai", "add_message", "BLOCKED", decision.Reason ?? "blocked", decision);
            throw new PolicyViolationException(decision.Reason ?? "blocked", decision.MatchedPattern);
        }

        PolicyAudit.Audit("openai", "add_message", "ALLOWED", decision: decision);
        return await _operations.AddMessageAsync(threadId, content, role, cancellationToken).ConfigureAwait(false);
    }

    public ValueTask<object?> RunAsync(string threadId, CancellationToken cancellationToken = default) =>
        _operations.RunAsync(threadId, cancellationToken);

    public ValueTask<object?> ListMessagesAsync(
        string threadId,
        string order = "desc",
        int limit = 1,
        CancellationToken cancellationToken = default) =>
        _operations.ListMessagesAsync(threadId, order, limit, cancellationToken);

    public ValueTask<object?> DeleteThreadAsync(string threadId, CancellationToken cancellationToken = default) =>
        _operations.DeleteThreadAsync(threadId, cancellationToken);
}
