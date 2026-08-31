from __future__ import annotations

import logging
from typing import Any, Dict, Iterable

from langchain_core.runnables import RunnableLambda

from app.schemas.search_result import SearchResult

logger = logging.getLogger(__name__)


def _log_results(
    message: str,
    stage: str,
    results: Iterable[SearchResult],
) -> None:
    """Log doc_id/score/rank for a retrieval stage -- never the query or
    article text. `request_id` is attached automatically by the JSON
    formatter, so this is enough to trace a stage's output back to a
    request without ever writing user content to stdout/CloudWatch.
    """
    logger.info(
        message,
        extra={
            "stage": stage,
            "results": [
                {"doc_id": r.article.id, "score": r.score, "rank": r.rank}
                for r in results
            ],
        },
    )


class LangChainRAGAdapter:
    """Thin wrappers from internal RAG components to LangChain Runnables."""

    @staticmethod
    def retriever_runnable(retriever):
        def retrieve(inputs: Dict[str, Any]) -> Dict[str, Any]:
            top_k = inputs.get("top_k")
            kwargs = {"top_k": top_k} if top_k is not None else {}
            results = retriever.search(query=inputs["query"], **kwargs)
            _log_results("Retrieved candidates", "retrieve", results)
            return {**inputs, "search_results": results}

        return RunnableLambda(retrieve)

    @staticmethod
    def reranker_runnable(reranker):
        def rerank(inputs: Dict[str, Any]) -> Dict[str, Any]:
            rerank_top_k = inputs.get("rerank_top_k")
            kwargs = {"top_k": rerank_top_k} if rerank_top_k is not None else {}
            results = reranker.rerank(
                query=inputs["query"],
                search_results=inputs["search_results"],
                **kwargs,
            )
            _log_results("Reranked candidates", "rerank", results)
            return {**inputs, "search_results": results}

        return RunnableLambda(rerank)

    @staticmethod
    def generator_runnable(generator):
        def generate(inputs: Dict[str, Any]) -> Dict[str, Any]:
            answer = generator.generate_text(
                query=inputs["query"],
                search_results=inputs["search_results"],
                chat_history=inputs.get("chat_history"),
            )
            return {**inputs, "answer": answer}

        return RunnableLambda(generate)
