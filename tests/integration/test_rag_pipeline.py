import os

import numpy as np
import psycopg2
import pytest
from psycopg2.extras import Json

from app.services.rag.orchestrator import RAGOrchestrator
from app.services.rag.retriever.pg_retriever import PGVectorRetriever


pytestmark = pytest.mark.integration

if os.getenv("RUN_INTEGRATION_TESTS") != "1":
    pytest.skip("skip integration tests by default", allow_module_level=True)


TEST_EMBEDDING = [0.1] * 384


@pytest.fixture(scope="function", autouse=True)
def seed_knowledge_base(test_database_url, clean_knowledge_base):
    with psycopg2.connect(test_database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO knowledge_base (
                    question_text,
                    content,
                    source,
                    author,
                    post_date,
                    language,
                    created_at,
                    tags,
                    link,
                    embedding
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, NOW(), %s::jsonb, %s, %s::vector
                );
            """, (
                "How do I apply for special consideration?",
                "Students can apply for special consideration through the university portal.",
                "University of Melbourne",
                "test",
                "2025-01-01",
                "en",
                Json(["unimelb", "special consideration"]),
                "https://students.unimelb.edu.au",
                TEST_EMBEDDING,
            ))

        conn.commit()


class FakeEmbeddingModel:
    def encode(self, texts, normalize_embeddings=True):
        return np.array([TEST_EMBEDDING for _ in texts])


class FakeReranker:
    def rerank(self, query, search_results, top_k=None):
        return search_results[:top_k]


class FakeGenerator:
    def generate_text(self, query, search_results, **kwargs):
        return f"fake answer for: {query}"

    def stream_text(self, query, search_results, **kwargs):
        yield f"fake answer for: {query}"


def test_rag_pipeline_end_to_end(test_database_url):
    retriever = PGVectorRetriever.__new__(PGVectorRetriever)
    retriever.conn = psycopg2.connect(test_database_url)
    retriever.table_name = "knowledge_base"
    retriever.model = FakeEmbeddingModel()

    reranker = FakeReranker()
    generator = FakeGenerator()

    orchestrator = RAGOrchestrator(
        retriever=retriever,
        reranker=reranker,
        generator=generator,
    )

    chain = orchestrator.as_chain()

    try:
        state = chain.invoke({
            "query": "How do I apply for special consideration?",
            "top_k": 5,
            "rerank_top_k": 3,
        })

        assert "fake answer" in state["answer"]
        assert len(state["answer"].strip()) > 0
        assert state["search_results"]

    finally:
        retriever.close()
