"""Command interpreter (AI-090 - AI-110). Not implemented yet.

Reserved so the shape of the next phase is visible. It will convert chat
messages into a discriminated union of typed commands -- BatchQueryCommand,
OrderQueryCommand, CreateOrderCommand, WorkflowActionCommand, UnknownCommand --
and classify each as read or write.

It will reuse `app.llm.provider.LLMProvider` unchanged. The same rule applies:
the model proposes a command, the backend validates and executes it. There is
no FORCE_TRANSITION action, and this service never performs the mutation.
"""
