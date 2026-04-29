using OpenAI.Assistants;

namespace PolicyEngine.Adapters.OpenAI;

public sealed class OpenAIKernel : BaseKernel
{
    public OpenAIKernel(GovernancePolicy policy)
        : base(policy)
    {
    }

    public override string Framework => "openai";

    public GovernedAssistant Wrap(IAssistantOperations operations) => new(this, operations);

#pragma warning disable OPENAI001
    public GovernedAssistant Wrap(AssistantClient client, string assistantId) =>
        Wrap(new OpenAIAssistantOperations(client, assistantId));

    public GovernedAssistant Wrap(Assistant assistant, AssistantClient client) =>
        Wrap(client, assistant.Id);
#pragma warning restore OPENAI001
}
