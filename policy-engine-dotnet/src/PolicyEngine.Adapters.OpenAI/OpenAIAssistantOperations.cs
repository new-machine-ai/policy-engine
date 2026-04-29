using System.ClientModel.Primitives;
using OpenAI.Assistants;

namespace PolicyEngine.Adapters.OpenAI;

#pragma warning disable OPENAI001
public sealed class OpenAIAssistantOperations : IAssistantOperations
{
    private readonly AssistantClient _client;

    public OpenAIAssistantOperations(AssistantClient client, string assistantId)
    {
        _client = client;
        AssistantId = assistantId;
    }

    public string AssistantId { get; }

    public async ValueTask<object?> CreateThreadAsync(CancellationToken cancellationToken = default) =>
        await _client.CreateThreadAsync(new ThreadCreationOptions(), cancellationToken).ConfigureAwait(false);

    public async ValueTask<object?> AddMessageAsync(
        string threadId,
        string content,
        string role = "user",
        CancellationToken cancellationToken = default) =>
        await _client.CreateMessageAsync(
            threadId,
            ToMessageRole(role),
            [MessageContent.FromText(content)],
            new MessageCreationOptions(),
            cancellationToken).ConfigureAwait(false);

    public async ValueTask<object?> RunAsync(string threadId, CancellationToken cancellationToken = default) =>
        await _client.CreateRunAsync(
            threadId,
            AssistantId,
            new RunCreationOptions(),
            cancellationToken).ConfigureAwait(false);

    public ValueTask<object?> ListMessagesAsync(
        string threadId,
        string order = "desc",
        int limit = 1,
        CancellationToken cancellationToken = default)
    {
        RequestOptions? requestOptions = cancellationToken.CanBeCanceled
            ? new RequestOptions { CancellationToken = cancellationToken }
            : null;

        return new ValueTask<object?>(_client.GetMessagesAsync(
            threadId,
            limit,
            order,
            after: null,
            before: null,
            requestOptions));
    }

    public async ValueTask<object?> DeleteThreadAsync(string threadId, CancellationToken cancellationToken = default) =>
        await _client.DeleteThreadAsync(threadId, cancellationToken).ConfigureAwait(false);

    private static MessageRole ToMessageRole(string role) =>
        role.Equals("assistant", StringComparison.OrdinalIgnoreCase)
            ? MessageRole.Assistant
            : MessageRole.User;
}
#pragma warning restore OPENAI001
