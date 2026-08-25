import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.schemas.search_result import SearchResult

from .adapters.langchain_adapter import LangChainRAGAdapter
from .generator.base import BaseGenerator
from .reranker.base import BaseReranker
from .retriever.base import BaseRetriever

logger = logging.getLogger(__name__)


class RAGOrchestrator:
    """Owns the RAG workflow and composes LangChain runnables."""

    def __init__(
        self,
        retriever: BaseRetriever,
        reranker: BaseReranker,
        generator: BaseGenerator,
    ):
        self.retriever = retriever
        self.reranker = reranker
        self.generator = generator
        self._chain = self._build_chain()

    def _build_chain(self):
        adapter = LangChainRAGAdapter()
        return (
            adapter.retriever_runnable(self.retriever)
            | adapter.reranker_runnable(self.reranker)
            | adapter.generator_runnable(self.generator)
        )

    def as_chain(self):
        """Return the reusable LangChain runnable pipeline."""
        return self._chain

    def close(self) -> None:
        """Release resources owned by the pipeline components."""
        for component in (
            self.retriever,
            self.reranker,
            self.generator,
        ):
            close = getattr(component, "close", None)
            if callable(close):
                close()

    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Run the LangChain runnable pipeline and return its full state."""
        return self._chain.invoke(inputs)

    def stream(self, inputs: Dict[str, Any]) -> Iterable[str]:
        """Stream from the generator after retrieve and rerank have completed."""
        state = (
            LangChainRAGAdapter.retriever_runnable(self.retriever)
            | LangChainRAGAdapter.reranker_runnable(self.reranker)
        ).invoke(inputs)

        yield from self.generator.stream_text(
            query=state["query"],
            search_results=state["search_results"],
            chat_history=state.get("chat_history"),
        )

    def run(
        self,
        query: str,
        *,
        top_k: Optional[int] = None,
        rerank_top_k: Optional[int] = None,
        chat_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[str, List[SearchResult]]:
        # No query text here -- request_id (already in the response header
        # and the chat_interactions primary key) is the join key back to
        # the query/answer. Keeps user content out of CloudWatch entirely.
        logger.info("Starting RAG pipeline")

        state = self.invoke(
            {
                "query": query,
                "top_k": top_k,
                "rerank_top_k": rerank_top_k,
                "chat_history": chat_history,
            }
        )

        logger.info("Generated response successfully.")
        return state["answer"], state["search_results"]
