"""End-to-end API integration test for POST /chat.

Exercises the real HTTP path through the full middleware stack (CORS ->
security headers -> request-id/access-log -> rate limit -> auth -> routing)
against a real PostgreSQL + pgvector retrieval. Only the paid OpenAI generator
and the embedding/reranker models are faked, so the test is free and
deterministic while still integrating the real ASGI stack and database.
"""
import os

import psycopg2
import pytest
from fastapi.testclient import TestClient
from psycopg2.extras import Json
from psycopg2.pool import ThreadedConnectionPool

from app.api.deps import get_rag_orchestrator
from app.core.config import settings
from app.core.middleware import SECURITY_HEADERS
from app.main import app
from app.services.rag.orchestrator import RAGOrchestrator
from app.services.rag.retriever.pg_retriever import PGVectorRetriever


pytestmark = pytest.mark.integration

if os.getenv("RUN_INTEGRATION_TESTS") != "1":
    pytest.skip("skip integration tests by default", allow_module_level=True)


TEST_EMBEDDING = [0.1] * 384
EMBEDDING_MODEL = "test-embedding-model"
EMBEDDING_REVISION = "revision-123"
API_KEY = "integration-test-key"


@pytest.fixture(scope="function", autouse=True)
def seed_knowledge_base(test_database_url, clean_knowledge_base):
    with psycopg2.connect(test_database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO knowledge_base (
                    question_text, content, source, link,
                    embedding_model, embedding_revision, embedding
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::vector);
                """,
                (
                    "How do I apply for special consideration?",
                    "Students apply for special consideration via the portal.",
                    "University of Melbourne",
                    "https://students.unimelb.edu.au",
                    EMBEDDING_MODEL,
                    EMBEDDING_REVISION,
                    TEST_EMBEDDING,
                ),
            )
        conn.commit()


class FakeEmbeddingModel:
    def encode(self, texts, normalize_embeddings=True):
        import numpy as np

        return np.array([TEST_EMBEDDING for _ in texts])


class FakeReranker:
    def rerank(self, query, search_results, top_k=None):
        return search_results[:top_k]


class FakeGenerator:
    def generate_text(self, query, search_results, **kwargs):
        return f"fake answer for: {query}"

    def stream_text(self, query, search_results, **kwargs):
        yield f"fake answer for: {query}"


@pytest.fixture
def real_stack_client(test_database_url, monkeypatch):
    """TestClient wired to a real DB retriever with only OpenAI/models faked."""
    monkeypatch.setattr(settings, "CHAT_API_KEY", API_KEY)

    retriever = PGVectorRetriever.__new__(PGVectorRetriever)
    retriever.pool = ThreadedConnectionPool(
        minconn=1, maxconn=1, dsn=test_database_url
    )
    retriever.table_name = "knowledge_base"
    retriever.model_name = EMBEDDING_MODEL
    retriever.model_revision = EMBEDDING_REVISION
    retriever.model = FakeEmbeddingModel()

    orchestrator = RAGOrchestrator(
        retriever=retriever,
        reranker=FakeReranker(),
        generator=FakeGenerator(),
    )

    app.dependency_overrides[get_rag_orchestrator] = lambda: orchestrator
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        retriever.close()


def test_chat_end_to_end_over_real_stack(real_stack_client):
    response = real_stack_client.post(
        "/chat",
        headers={"X-API-Key": API_KEY},
        json={"message": "How do I apply for special consideration?"},
    )

    assert response.status_code == 200
    payload = response.json()
    # Answer comes from the fake generator; sources come from real pgvector.
    assert "fake answer" in payload["answer"]
    assert len(payload["sources"]) == 1
    assert "special consideration" in payload["sources"][0]["article"]["text"]

    # Cross-cutting middleware composed correctly on a real success response.
    assert response.headers["X-Request-ID"]
    for name, value in SECURITY_HEADERS:
        assert response.headers[name.decode()] == value.decode()


def test_rate_limit_429_still_carries_middleware_headers(
    real_stack_client, monkeypatch
):
    monkeypatch.setattr(settings, "CHAT_RATE_LIMIT", "1/minute")

    first = real_stack_client.post(
        "/chat",
        headers={"X-API-Key": API_KEY},
        json={"message": "How do I apply for special consideration?"},
    )
    second = real_stack_client.post(
        "/chat",
        headers={"X-API-Key": API_KEY},
        json={"message": "How do I apply for special consideration?"},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json() == {
        "error": {
            "code": "rate_limited",
            "message": "Too many requests. Please slow down and try again shortly.",
        }
    }
    # The 429 rejection still passes back out through the outer middleware,
    # so security headers and the request id must be present on it too.
    assert second.headers["X-Request-ID"]
    for name, value in SECURITY_HEADERS:
        assert second.headers[name.decode()] == value.decode()
