from functools import lru_cache

from fastapi import HTTPException, status

from app.services.rag.orchestrator import RAGOrchestrator


@lru_cache(maxsize=1)
def _build_rag_orchestrator() -> RAGOrchestrator:
    """Build the expensive RAG pipeline once, on the first chat request."""
    # Keep heavyweight imports lazy so the health endpoint starts quickly.
    from app.services.rag.generator.chatgpt_generator import ChatGPTGenerator
    from app.services.rag.reranker.cross_encoder_reranker import CrossEncoderReranker
    from app.services.rag.retriever.pg_retriever import PGVectorRetriever

    return RAGOrchestrator(
        retriever=PGVectorRetriever(),
        reranker=CrossEncoderReranker(),
        generator=ChatGPTGenerator(),
    )


def get_rag_orchestrator() -> RAGOrchestrator:
    """FastAPI dependency that exposes startup failures as a useful 503."""
    try:
        return _build_rag_orchestrator()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"RAG service is unavailable: {exc}",
        ) from exc


def close_rag_orchestrator() -> None:
    """Close the cached pipeline without initializing it during shutdown."""
    if _build_rag_orchestrator.cache_info().currsize == 0:
        return

    try:
        _build_rag_orchestrator().close()
    finally:
        _build_rag_orchestrator.cache_clear()
