from functools import lru_cache
import secrets
from typing import Annotated

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import settings
from app.services.rag.orchestrator import RAGOrchestrator


chat_api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
)


def require_internal_api_key(
    provided_api_key: Annotated[
        str | None,
        Security(chat_api_key_header),
    ],
) -> None:
    """Require the shared API key used by internal test clients."""
    configured_api_key = settings.CHAT_API_KEY
    if not configured_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured",
        )
    if (
        provided_api_key is None
        or not secrets.compare_digest(
            provided_api_key,
            configured_api_key,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


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


def preload_rag_orchestrator() -> None:
    """Build the pipeline during startup so no request has to pay for it.

    The public entry point for the app lifespan: callers outside this module
    should not reach for the cached builder by its private name.
    """
    _build_rag_orchestrator()


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
