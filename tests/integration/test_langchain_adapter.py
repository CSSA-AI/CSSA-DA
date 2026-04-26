# tests/integration/test_langchain_rag_adapter.py

import os
import pytest
import psycopg2
from sentence_transformers import SentenceTransformer

from app.services.rag.adapters.langchain_adapter import LangChainRAGAdapter
from app.services.rag.reranker.cross_encoder_reranker import CrossEncoderReranker
from app.services.rag.retriever.pg_retriever import PGVectorRetriever


pytestmark = pytest.mark.integration

if os.getenv("RUN_INTEGRATION_TESTS") != "1":
    pytest.skip("skip integration tests by default", allow_module_level=True)


@pytest.fixture(scope="function", autouse=True)
def setup_knowledge_base():
    database_url = os.environ["DATABASE_URL"]

    model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

    embedding = model.encode(
        ["墨尔本大学 special consideration 怎么申请？"],
        normalize_embeddings=True,
    )[0].tolist()

    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute("DROP TABLE IF EXISTS knowledge_base;")

            cur.execute("""
                CREATE TABLE knowledge_base (
                    id SERIAL PRIMARY KEY,
                    question_text TEXT,
                    content TEXT,
                    source TEXT,
                    author TEXT,
                    post_date DATE,
                    language TEXT,
                    created_at TIMESTAMP,
                    tags TEXT[],
                    link TEXT,
                    embedding vector(384)
                );
            """)

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
                    %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s::vector
                );
            """, (
                "墨尔本大学 special consideration 怎么申请？",
                "墨尔本大学 Special consideration 通常需要在规定时间内通过学校系统提交申请，并上传相关证明材料。",
                "University of Melbourne",
                "test",
                "2025-01-01",
                "zh",
                ["unimelb", "special consideration"],
                "https://students.unimelb.edu.au",
                embedding,
            ))

        conn.commit()


class FakeGenerator:
    def generate_text(self, query, search_results, **kwargs):
        return f"fake answer for: {query}"

    def stream_text(self, query, search_results, **kwargs):
        yield f"fake answer for: {query}"


def test_langchain_rag_adapter_end_to_end():
    retriever = PGVectorRetriever()
    reranker = CrossEncoderReranker()
    generator = FakeGenerator()

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

        assert "fake answer" in answer
        assert len(answer.strip()) > 0

    finally:
        retriever.close()