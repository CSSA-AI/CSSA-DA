from dataclasses import dataclass
from functools import lru_cache
import logging
import secrets
from typing import Annotated, Literal

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from slowapi.util import get_remote_address

from app.core.config import settings
from app.services.rag.orchestrator import RAGOrchestrator


logger = logging.getLogger(__name__)

chat_api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
)


@dataclass(frozen=True)
class Principal:
    """Who made this request, decided once while authenticating it.

    v1 has a single shared key, so every caller looks the same and there is
    nothing here worth knowing. v2 needs the answer in three places at once —
    which bucket to rate limit against, what to store in
    chat_interactions.user_id, and which auth path to log — and resolving it
    once here is what keeps those three from each parsing the request again.

    Frozen because this records a fact about the request: nothing downstream
    should be able to rewrite who the caller was.
    """

    kind: Literal["internal"]
    user_id: str | None
    rate_limit_key: str


def require_caller(
    request: Request,
    provided_api_key: Annotated[
        str | None,
        Security(chat_api_key_header),
    ],
) -> Principal:
    """Require the shared API key, and say who the caller turned out to be."""
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

    # The "ip:" prefix looks redundant while addresses are the only source of
    # keys. It is here because v2 adds "user:<id>": without a prefix, a user
    # whose id happened to be 10.0.0.5 would share a bucket with that address.
    principal = Principal(
        kind="internal",
        user_id=None,
        rate_limit_key=f"ip:{get_remote_address(request)}",
    )
    # Also published on request.state because the rate limiter cannot reach a
    # dependency's return value: slowapi wraps the endpoint from outside, so
    # it only ever sees the request. See chat_rate_limit_key.
    request.state.principal = principal
    return principal


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
        # The exception text can contain connection strings, hostnames, or
        # driver internals — log it, but never put it in the response body.
        logger.exception("RAG orchestrator is unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG service is unavailable. Please try again later.",
        ) from exc


def close_rag_orchestrator() -> None:
    """Close the cached pipeline without initializing it during shutdown."""
    if _build_rag_orchestrator.cache_info().currsize == 0:
        return

    try:
        _build_rag_orchestrator().close()
    finally:
        _build_rag_orchestrator.cache_clear()
