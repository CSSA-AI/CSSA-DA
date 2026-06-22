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

        kwargs = {"top_k": top_k} if top_k is not None else {}
        results = self.retriever.search(query=query, **kwargs)

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

        kwargs = {"top_k": rerank_top_k} if rerank_top_k is not None else {}
        results = self.reranker.rerank(
            query=query, search_results=inputs["search_results"], **kwargs
        )

        return {
            **inputs,
            "search_results": results,
        }

    # ========= step 3: generate =========
    def _generate(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        answer = self.generator.generate_text(
            query=inputs["query"],
            search_results=inputs["search_results"],
            chat_history=inputs.get("chat_history"),
        )
        return {**inputs, "answer": answer}

    # ========= streaming =========
    def stream(self, inputs: Dict[str, Any]) -> Iterable[str]:
        state = self._rerank(self._retrieve(inputs))
        yield from self.generator.stream_text(
            query=state["query"],
            search_results=state["search_results"],
            chat_history=state.get("chat_history"),
        )

    def retriever_runnable(self):
        return RunnableLambda(self._retrieve)

    def reranker_runnable(self):
        return RunnableLambda(self._rerank)

    def generator_runnable(self):
        return RunnableLambda(self._generate)

    # ========= LCEL chain =========
    def as_chain(self):
        return (
            RunnablePassthrough()
            | self.retriever_runnable()
            | self.reranker_runnable()
            | self.generator_runnable()
        )

    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return self.as_chain().invoke(inputs)
