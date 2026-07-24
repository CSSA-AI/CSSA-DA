import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_rag_orchestrator, require_internal_api_key
from app.core.logging import AppJsonLogFormatter
from app.core.middleware import SECURITY_HEADERS
from app.main import app
from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.errors import RetrievalUnavailableError


class LoggingOrchestrator:
    """Stub orchestrator that logs from deep inside the request call stack."""

    def run(self, query, **kwargs):
        logging.getLogger("app.services.rag.orchestrator").info(
            "deep pipeline log"
        )
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
    """Stub orchestrator that raises a handled RAG service error."""

    def run(self, query, **kwargs):
        raise RetrievalUnavailableError("internal detail must stay private")


def client() -> TestClient:
    app.dependency_overrides[get_rag_orchestrator] = lambda: (
        LoggingOrchestrator()
    )
    app.dependency_overrides[require_internal_api_key] = lambda: None
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def captured_app_logs():
    """Collect JSON log lines emitted by the "app" logger during a test.

    caplog cannot be used directly: configure_app_logging sets
    propagate=False on the "app" logger, so records never reach the root
    logger where caplog listens.
    """
    formatted_lines: list[str] = []

    class CollectingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            formatted_lines.append(self.format(record))

    handler = CollectingHandler()
    handler.setFormatter(AppJsonLogFormatter())
    app_logger = logging.getLogger("app")
    app_logger.addHandler(handler)
    yield formatted_lines
    app_logger.removeHandler(handler)


def test_request_id_generated_when_absent():
    response = client().get("/health")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


def test_request_id_echoed_when_provided():
    response = client().get(
        "/health",
        headers={"X-Request-ID": "my-custom-id"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "my-custom-id"


def test_access_log_emitted_with_request_metadata(captured_app_logs):
    response = client().get("/health")

    access_logs = [
        json.loads(line)
        for line in captured_app_logs
        if "request completed" in line
    ]
    assert len(access_logs) == 1
    access_log = access_logs[0]
    assert access_log["method"] == "GET"
    assert access_log["path"] == "/health"
    assert access_log["status_code"] == 200
    assert access_log["duration_ms"] >= 0
    assert access_log["request_id"] == response.headers["X-Request-ID"]


def test_deep_log_carries_same_request_id_as_response(captured_app_logs):
    response = client().post(
        "/chat",
        headers={"X-Request-ID": "trace-me-deeply"},
        json={"message": "How do I enrol?"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace-me-deeply"
    deep_logs = [
        json.loads(line)
        for line in captured_app_logs
        if "deep pipeline log" in line
    ]
    assert len(deep_logs) == 1
    assert deep_logs[0]["logger"] == "app.services.rag.orchestrator"
    assert deep_logs[0]["request_id"] == "trace-me-deeply"


def test_request_ids_do_not_leak_between_requests(captured_app_logs):
    test_client = client()

    first = test_client.get(
        "/health",
        headers={"X-Request-ID": "first-request"},
    )
    second = test_client.get("/health")

    assert first.headers["X-Request-ID"] == "first-request"
    assert second.headers["X-Request-ID"] != "first-request"

    access_logs = [
        json.loads(line)
        for line in captured_app_logs
        if "request completed" in line
    ]
    assert [log["request_id"] for log in access_logs] == [
        first.headers["X-Request-ID"],
        second.headers["X-Request-ID"],
    ]


def test_security_headers_present_on_success():
    response = client().get("/health")

    assert response.status_code == 200
    for name, value in SECURITY_HEADERS:
        assert response.headers[name.decode()] == value.decode()


def test_security_headers_present_on_error():
    app.dependency_overrides[get_rag_orchestrator] = lambda: (
        FailingOrchestrator()
    )
    app.dependency_overrides[require_internal_api_key] = lambda: None
    response = TestClient(app).post(
        "/chat",
        json={"message": "How do I enrol?"},
    )

    assert response.status_code == 503
    for name, value in SECURITY_HEADERS:
        assert response.headers[name.decode()] == value.decode()


def test_cors_preflight_allows_configured_origin():
    response = client().options(
        "/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.headers["Access-Control-Allow-Origin"] == (
        "http://localhost:3000"
    )


def test_cors_omits_headers_for_unconfigured_origin():
    response = client().options(
        "/chat",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert "Access-Control-Allow-Origin" not in response.headers
