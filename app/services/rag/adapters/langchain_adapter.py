# app/services/rag/adapters/langchain_adapter.py

from __future__ import annotations

from typing import Any, Dict, Iterable

from langchain_core.runnables import RunnableLambda, RunnablePassthrough


class LangChainRAGAdapter:
    """
    把 core RAG（retriever / reranker / generator）
    包装成 LangChain LCEL Runnable。
    """

    def __init__(self, retriever, generator, reranker=None):
        self.retriever = retriever
        self.reranker = reranker
        self.generator = generator

    # ========= step 1: retrieve =========
    def _retrieve(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        query = inputs["query"]
        top_k = inputs.get("top_k")

        results = self.retriever.search(
            query=query,
            top_k=top_k,
        )

        return {
            **inputs,
            "search_results": results,
        }

    # ========= step 2: rerank =========
    def _rerank(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if self.reranker is None:
            return inputs

        query = inputs["query"]
        rerank_top_k = inputs.get("rerank_top_k")

        results = self.reranker.rerank(
            query=query,
            search_results=inputs["search_results"],
            top_k=rerank_top_k,
        )

        return {
            **inputs,
            "search_results": results,
        }

    # ========= step 3: generate =========
    def _generate(self, inputs: Dict[str, Any]) -> str:
        return self.generator.generate_text(
            query=inputs["query"],
            search_results=inputs["search_results"],
            chat_history=inputs.get("chat_history"),
        )

    # ========= streaming =========
    def stream(self, inputs: Dict[str, Any]) -> Iterable[str]:
        yield from self.generator.stream_text(
            query=inputs["query"],
            search_results=inputs["search_results"],
            chat_history=inputs.get("chat_history"),
        )

    # ========= LCEL chain =========
    def as_chain(self):
        return (
            RunnablePassthrough()
            | RunnableLambda(self._retrieve)
            | RunnableLambda(self._rerank)
            | RunnableLambda(self._generate)
        )