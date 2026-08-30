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
from app.core.config import rag_config, settings
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
        "/v1/chat",
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
        "/v1/chat",
        headers={"X-API-Key": API_KEY},
        json={"message": "How do I apply for special consideration?"},
    )
    second = real_stack_client.post(
        "/v1/chat",
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


def _fetch_interactions(database_url):
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT request_id, created_at, query, answer, retrieved, config
                FROM chat_interactions
                ORDER BY created_at;
                """
            )
            return cur.fetchall()


def test_chat_writes_one_interaction_row_over_the_real_stack(
    real_stack_client,
    test_database_url,
    monkeypatch,
):
    """The data line's feeding tube, end to end against a real database."""
    monkeypatch.setattr(settings, "DATABASE_URL", test_database_url)
    monkeypatch.setattr(settings, "GIT_SHA", "integration-sha")
    monkeypatch.setattr(settings, "CORPUS_SHA256", "integration-corpus")

    response = real_stack_client.post(
        "/v1/chat",
        headers={"X-API-Key": API_KEY},
        json={
            "message": "How do I apply for special consideration?",
            "top_k": 5,
            "rerank_top_k": 3,
        },
    )

    assert response.status_code == 200

    rows = _fetch_interactions(test_database_url)
    assert len(rows) == 1
    request_id, created_at, query, answer, retrieved, config = rows[0]

    # The response header is the join key back to this row and to the
    # request's log lines — if these ever diverge, a user reporting a bad
    # answer becomes untraceable.
    assert request_id == response.headers["X-Request-ID"]
    assert created_at is not None
    assert query == "How do I apply for special consideration?"
    assert "fake answer" in answer

    assert len(retrieved) == 1
    assert set(retrieved[0]) == {"doc_id", "score", "rank"}
    assert retrieved[0]["rank"] == 1

    assert config["top_k"] == 5
    assert config["rerank_top_k"] == 3
    # The fingerprint records the deployed rag-config.yaml, not whatever
    # object happens to be wired in — this fixture builds the retriever by
    # hand with a fake model, which no production path does (deps.py always
    # constructs it from the same config).
    assert config["embedding_model"] == rag_config["retriever"]["embedding_model"]
    assert config["reranker_model"] == rag_config["reranker"]["model_name"]
    assert config["git_sha"] == "integration-sha"
    assert config["corpus_sha256"] == "integration-corpus"
    assert config["prompt_version"].startswith("sha256:")


def test_chat_still_answers_when_the_interaction_write_fails(
    real_stack_client,
    test_database_url,
    monkeypatch,
):
    """A recording outage is invisible to the user and loses no query."""
    monkeypatch.setattr(
        settings,
        "DATABASE_URL",
        "postgresql://invalid:invalid@127.0.0.1:1/nonexistent",
    )

    response = real_stack_client.post(
        "/v1/chat",
        headers={"X-API-Key": API_KEY},
        json={"message": "How do I apply for special consideration?"},
    )

    assert response.status_code == 200
    assert "fake answer" in response.json()["answer"]
    assert _fetch_interactions(test_database_url) == []


def test_a_reused_request_id_does_not_overwrite_the_first_row(
    real_stack_client,
    test_database_url,
    monkeypatch,
):
    """The middleware honours a caller-supplied X-Request-ID, so collisions
    are reachable from outside. The first row must win."""
    monkeypatch.setattr(settings, "DATABASE_URL", test_database_url)
    headers = {"X-API-Key": API_KEY, "X-Request-ID": "reused-id"}

    first = real_stack_client.post(
        "/v1/chat",
        headers=headers,
        json={"message": "How do I apply for special consideration?"},
    )
    second = real_stack_client.post(
        "/v1/chat",
        headers=headers,
        json={"message": "A different question entirely?"},
    )

    assert first.status_code == 200
    assert second.status_code == 200

    rows = _fetch_interactions(test_database_url)
    assert len(rows) == 1
    assert rows[0][0] == "reused-id"
    assert rows[0][2] == "How do I apply for special consideration?"
