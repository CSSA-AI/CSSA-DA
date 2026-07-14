import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_rag_orchestrator
from app.main import app
from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.readiness import ReadinessCheck
from app.services.rag.errors import (
    GenerationTimeoutError,
    GenerationUnavailableError,
    RetrievalUnavailableError,
)
from app.services.system_status import (
    PipelineMetadataStatus,
    SystemStatus,
)


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


class FailingOrchestrator:
    def __init__(self, error):
        self.error = error

    def run(self, query, **kwargs):
        raise self.error


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


def test_status_reports_readiness_and_pipeline_metadata(monkeypatch):
    monkeypatch.setattr(
        "app.main.get_system_status",
        lambda: SystemStatus(
            api="ok",
            rag_ready=True,
            readiness=ReadinessCheck(
                status="ready",
                database="ok",
                knowledge_base_rows=3,
                embedding_model="test-model",
                embedding_revision="revision-123",
            ),
            pipeline_metadata=PipelineMetadataStatus(
                latest_run=None,
            ),
        ),
    )

    response = client().get("/status")

    assert response.status_code == 200
    assert response.json()["api"] == "ok"
    assert response.json()["rag_ready"] is True
    assert response.json()["readiness"]["status"] == "ready"
    assert response.json()["pipeline_metadata"] == {
        "available": True,
        "latest_run": None,
    }


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


@pytest.mark.parametrize(
    ("error", "status_code", "error_code"),
    [
        (
            RetrievalUnavailableError("database URL must stay private"),
            503,
            "retrieval_unavailable",
        ),
        (
            GenerationUnavailableError("provider details must stay private"),
            503,
            "generation_unavailable",
        ),
        (
            GenerationTimeoutError("provider timeout details"),
            504,
            "generation_timeout",
        ),
    ],
)
def test_chat_returns_safe_service_errors(
    error,
    status_code,
    error_code,
):
    app.dependency_overrides[get_rag_orchestrator] = lambda: (
        FailingOrchestrator(error)
    )

    response = TestClient(app).post(
        "/chat",
        json={"message": "How do I enrol?"},
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code
    assert str(error) not in response.text
