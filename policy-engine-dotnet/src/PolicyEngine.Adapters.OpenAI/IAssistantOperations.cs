namespace PolicyEngine.Adapters.OpenAI;

public interface IAssistantOperations
{
    string AssistantId { get; }

    ValueTask<object?> CreateThreadAsync(CancellationToken cancellationToken = default);

    ValueTask<object?> AddMessageAsync(
        string threadId,
        string content,
        string role = "user",
        CancellationToken cancellationToken = default);

    ValueTask<object?> RunAsync(string threadId, CancellationToken cancellationToken = default);

    ValueTask<object?> ListMessagesAsync(
        string threadId,
        string order = "desc",
        int limit = 1,
        CancellationToken cancellationToken = default);

    ValueTask<object?> DeleteThreadAsync(string threadId, CancellationToken cancellationToken = default);
}
