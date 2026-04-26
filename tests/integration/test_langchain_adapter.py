# tests/integration/test_langchain_rag_adapter.py

import pytest

from app.services.rag.adapters.langchain_adapter import LangChainRAGAdapter
from app.services.rag.generator.chatgpt_generator import ChatGPTGenerator
from app.services.rag.reranker.cross_encoder_reranker import CrossEncoderReranker
from app.services.rag.retriever.pg_retriever import PGVectorRetriever


@pytest.mark.integration
def test_langchain_rag_adapter_end_to_end():
    retriever = PGVectorRetriever()
    reranker = CrossEncoderReranker()
    generator = ChatGPTGenerator()

    adapter = LangChainRAGAdapter(
        retriever=retriever,
        reranker=reranker,
        generator=generator,
    )

    chain = adapter.as_chain()

    try:
        answer = chain.invoke({
            "query": "墨尔本大学 special consideration 怎么申请？",
            "top_k": 5,
            "rerank_top_k": 3,
        })

        assert isinstance(answer, str)
        assert len(answer.strip()) > 0

    finally:
        retriever.close()