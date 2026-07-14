class RAGServiceError(RuntimeError):
    """Base exception for expected RAG service failures."""

    code = "rag_service_error"
    public_message = "The RAG service is temporarily unavailable."


class RetrievalUnavailableError(RAGServiceError):
    code = "retrieval_unavailable"
    public_message = "The retrieval service is temporarily unavailable."


class GenerationUnavailableError(RAGServiceError):
    code = "generation_unavailable"
    public_message = "The generation service is temporarily unavailable."


class GenerationTimeoutError(RAGServiceError):
    code = "generation_timeout"
    public_message = "The generation service timed out."
