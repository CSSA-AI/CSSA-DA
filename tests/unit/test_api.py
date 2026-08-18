import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from app.api.deps import get_rag_orchestrator, require_internal_api_key
from app.core.config import settings
from app.main import app
from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.readiness import ReadinessCheck
from app.services.rag.errors import (
    GenerationTimeoutError,
    GenerationUnavailableError,
    RetrievalUnavailableError,
)
from app.services.rag.model_registry import ModelRegistryStatus, model_registry
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
    app.dependency_overrides[require_internal_api_key] = lambda: None
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


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
            models=ModelRegistryStatus(
                embedding="ready",
                reranker="ready",
            ),
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
        "models": {
            "status": "ready",
            "embedding": "ready",
            "reranker": "ready",
        },
    }


def test_lifespan_preloads_models_and_orchestrator(monkeypatch):
    preload_models = MagicMock()
    build_rag_orchestrator = MagicMock()

    monkeypatch.setattr(
        model_registry,
        "preload_models",
        preload_models,
    )
    monkeypatch.setattr(
        "app.main._build_rag_orchestrator",
        build_rag_orchestrator,
    )

    with TestClient(app) as test_client:
        preload_models.assert_called_once_with()
        build_rag_orchestrator.assert_called_once_with()

        response = test_client.get("/health")




def test_model_preload_failure_does_not_break_health(monkeypatch):
    monkeypatch.setattr(
        model_registry,
        "preload_models",
        MagicMock(side_effect=RuntimeError("model failed")),
    )

    with TestClient(app) as test_client:
        response = test_client.get("/health")

    assert response.status_code == 200


def test_ready_returns_503_when_database_or_data_are_not_ready(monkeypatch):
    monkeypatch.setattr(
        "app.main.check_readiness",
        lambda: ReadinessCheck(
            status="not_ready",
            database="ok",
            knowledge_base_rows=0,
            embedding_model="test-model",
            embedding_revision="revision-123",
            models=ModelRegistryStatus(
                embedding="ready",
                reranker="ready",
            ),
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
                models=ModelRegistryStatus(
                    embedding="ready",
                    reranker="ready",
                ),
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
        "/v1/chat",
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


def test_unversioned_chat_path_is_gone():
    # This change has two halves: /v1/chat exists AND /chat no longer does.
    # Without this, nothing stops the unversioned route being re-added later.
    response = client().post("/chat", json={"message": "How do I enrol?"})

    assert response.status_code == 404


def test_chat_rejects_an_empty_message():
    response = client().post("/v1/chat", json={"message": ""})

    assert response.status_code == 422


def test_chat_rejects_a_chat_history_message_over_the_length_cap():
    response = client().post(
        "/v1/chat",
        json={
            "message": "How do I enrol?",
            "chat_history": [{"role": "user", "content": "x" * 4_001}],
        },
    )

    assert response.status_code == 422


def test_chat_accepts_a_chat_history_message_at_the_length_cap():
    response = client().post(
        "/v1/chat",
        json={
            "message": "How do I enrol?",
            "chat_history": [{"role": "user", "content": "x" * 4_000}],
        },
    )

    assert response.status_code == 200


def test_chat_rejects_chat_history_over_the_item_count_cap():
    response = client().post(
        "/v1/chat",
        json={
            "message": "How do I enrol?",
            "chat_history": [
                {"role": "user", "content": "hi"} for _ in range(21)
            ],
        },
    )

    assert response.status_code == 422


def test_chat_accepts_chat_history_at_the_item_count_cap():
    response = client().post(
        "/v1/chat",
        json={
            "message": "How do I enrol?",
            "chat_history": [
                {"role": "user", "content": "hi"} for _ in range(20)
            ],
        },
    )

    assert response.status_code == 200


@pytest.mark.parametrize("provided_api_key", [None, "wrong-key"])
def test_chat_rejects_invalid_or_missing_api_key(
    monkeypatch,
    provided_api_key,
):
    monkeypatch.setattr(settings, "CHAT_API_KEY", "expected-key")
    app.dependency_overrides[get_rag_orchestrator] = lambda: StubOrchestrator()
    headers = (
        {"X-API-Key": provided_api_key}
        if provided_api_key is not None
        else {}
    )

    response = TestClient(app).post(
        "/v1/chat",
        headers=headers,
        json={"message": "How do I enrol?"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}


def test_chat_returns_503_when_api_key_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "CHAT_API_KEY", None)
    app.dependency_overrides[get_rag_orchestrator] = lambda: StubOrchestrator()

    response = TestClient(app).post(
        "/v1/chat",
        headers={"X-API-Key": "any-key"},
        json={"message": "How do I enrol?"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "API authentication is not configured"
    }


def test_chat_accepts_configured_api_key(monkeypatch):
    monkeypatch.setattr(settings, "CHAT_API_KEY", "expected-key")
    app.dependency_overrides[get_rag_orchestrator] = lambda: StubOrchestrator()

    response = TestClient(app).post(
        "/v1/chat",
        headers={"X-API-Key": "expected-key"},
        json={"message": "How do I enrol?"},
    )

    assert response.status_code == 200


def test_status_requires_api_key(monkeypatch):
    monkeypatch.setattr(settings, "CHAT_API_KEY", "expected-key")

    response = TestClient(app).get("/status")

    assert response.status_code == 401


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
    app.dependency_overrides[require_internal_api_key] = lambda: None

    response = TestClient(app).post(
        "/v1/chat",
        json={"message": "How do I enrol?"},
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code
    assert str(error) not in response.text
