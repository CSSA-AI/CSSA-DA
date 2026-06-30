from __future__ import annotations

from typing import Any, Dict

from langchain_core.runnables import RunnableLambda


class LangChainRAGAdapter:
    """Thin wrappers from internal RAG components to LangChain Runnables."""

    @staticmethod
    def retriever_runnable(retriever):
        def retrieve(inputs: Dict[str, Any]) -> Dict[str, Any]:
            top_k = inputs.get("top_k")
            kwargs = {"top_k": top_k} if top_k is not None else {}
            results = retriever.search(query=inputs["query"], **kwargs)
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
