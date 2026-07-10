from fastapi.testclient import TestClient

from app.api.deps import get_rag_orchestrator
from app.main import app
from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.readiness import ReadinessCheck


class StubOrchestrator:
    def run(self, query, **kwargs):
        return (
            f"Answer for: {query}",
            [
                SearchResult(
                    article=Article(
                        text="Relevant article",
                        questions=["Example question"],
                        source="test",
                        link="https://example.com/article",
                    ),
                    score=0.95,
                    rank=1,
                )
            ],
        )


def client() -> TestClient:
    app.dependency_overrides[get_rag_orchestrator] = lambda: StubOrchestrator()
    return TestClient(app)


def test_health():
    response = client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_200_when_database_and_data_are_ready(monkeypatch):
    monkeypatch.setattr(
        "app.main.check_readiness",
        lambda: ReadinessCheck(
            status="ready",
            database="ok",
            knowledge_base_rows=3,
            embedding_model="test-model",
            embedding_revision="revision-123",
        ),
    )

    response = client().get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "ok",
        "knowledge_base_rows": 3,
        "embedding_model": "test-model",
        "embedding_revision": "revision-123",
    }


def test_ready_returns_503_when_database_or_data_are_not_ready(monkeypatch):
    monkeypatch.setattr(
        "app.main.check_readiness",
        lambda: ReadinessCheck(
            status="not_ready",
            database="ok",
            knowledge_base_rows=0,
            embedding_model="test-model",
            embedding_revision="revision-123",
            reason="knowledge_base has no rows",
        ),
    )

    response = client().get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["reason"] == "knowledge_base has no rows"


def test_chat_returns_answer_and_sources():
    response = client().post(
        "/chat",
        json={
            "message": "How do I enrol?",
            "chat_history": [{"role": "user", "content": "Hello"}],
            "top_k": 5,
            "rerank_top_k": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "Answer for: How do I enrol?"
    assert payload["sources"][0]["article"]["source"] == "test"
    assert payload["sources"][0]["score"] == 0.95


def test_chat_rejects_an_empty_message():
    response = client().post("/chat", json={"message": ""})

    assert response.status_code == 422
