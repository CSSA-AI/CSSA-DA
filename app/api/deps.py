import json
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, status

from app.schemas.article import Article
from app.services.rag.orchestrator import RAGOrchestrator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = PROJECT_ROOT / "data" / "demo_data.json"


@lru_cache(maxsize=1)
def _build_rag_orchestrator() -> RAGOrchestrator:
    """Build the expensive RAG pipeline once, on the first chat request."""
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"RAG data file not found: {DATA_PATH}")

    with DATA_PATH.open(encoding="utf-8") as data_file:
        articles = [Article(**item) for item in json.load(data_file)]

    # Keep heavyweight imports lazy so the health endpoint starts quickly.
    from app.services.rag.generator.chatgpt_generator import ChatGPTGenerator
    from app.services.rag.reranker.cross_encoder_reranker import CrossEncoderReranker
    from app.services.rag.retriever.faiss_retriever import FAISSRetriever

    return RAGOrchestrator(
        retriever=FAISSRetriever(input_list=articles),
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
