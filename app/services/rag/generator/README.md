# Generator

The generator is framework independent. It accepts a query, ranked
`SearchResult` objects, and optional plain-dictionary chat history, then calls the
OpenAI SDK for synchronous or streaming output.

Conversation persistence, tracing, and LangChain message conversion belong to the
calling application or `rag/adapters/langchain_adapter.py`.
