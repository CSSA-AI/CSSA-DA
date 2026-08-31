import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_rag_orchestrator, require_internal_api_key
from app.core.config import settings
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


class UnexpectedlyFailingOrchestrator:
    """Stub orchestrator that raises an unhandled, non-RAG exception."""

    def run(self, query, **kwargs):
        raise RuntimeError("db password=supersecret must stay private")


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
        "/v1/chat",
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
        "/v1/chat",
        json={"message": "How do I enrol?"},
    )

    assert response.status_code == 503
    for name, value in SECURITY_HEADERS:
        assert response.headers[name.decode()] == value.decode()


def test_cors_preflight_allows_configured_origin():
    response = client().options(
        "/v1/chat",
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
        "/v1/chat",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert "Access-Control-Allow-Origin" not in response.headers


def test_chat_rate_limit_returns_safe_429(monkeypatch):
    monkeypatch.setattr(settings, "CHAT_RATE_LIMIT", "2/minute")
    test_client = client()

    first = test_client.post("/v1/chat", json={"message": "hi"})
    second = test_client.post("/v1/chat", json={"message": "hi"})
    third = test_client.post("/v1/chat", json={"message": "hi"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.json() == {
        "error": {
            "code": "rate_limited",
            "message": "Too many requests. Please slow down and try again shortly.",
        }
    }


def test_chat_global_rate_limit_returns_safe_429(monkeypatch):
    # Per-IP limit stays at its loose default (10/minute), so the third
    # request can only be rejected by the site-wide counter.
    monkeypatch.setattr(settings, "CHAT_GLOBAL_RATE_LIMIT", "2/day")
    test_client = client()

    first = test_client.post("/v1/chat", json={"message": "hi"})
    second = test_client.post("/v1/chat", json={"message": "hi"})
    third = test_client.post("/v1/chat", json={"message": "hi"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.json() == {
        "error": {
            "code": "rate_limited",
            "message": "Too many requests. Please slow down and try again shortly.",
        }
    }


def test_chat_global_rate_limit_is_shared_across_ips(monkeypatch):
    # Three requests from three different IPs: the per-IP layer never trips
    # (each IP is on its own counter), so the third 429 proves every client
    # shares one site-wide counter — rotating IPs cannot bypass it.
    monkeypatch.setattr(settings, "CHAT_GLOBAL_RATE_LIMIT", "2/day")
    client()  # installs the dependency overrides on the shared app

    first = TestClient(app, client=("10.0.0.1", 50000)).post(
        "/v1/chat", json={"message": "hi"}
    )
    second = TestClient(app, client=("10.0.0.2", 50000)).post(
        "/v1/chat", json={"message": "hi"}
    )
    third = TestClient(app, client=("10.0.0.3", 50000)).post(
        "/v1/chat", json={"message": "hi"}
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429


def test_per_ip_429s_do_not_burn_the_global_budget(monkeypatch):
    # Decorator-order regression sentinel: slowapi charges counters before
    # judging them and evaluates the bottom decorator first, so the per-IP
    # layer must reject spam BEFORE the site-wide counter is touched. If the
    # decorators on /chat are ever swapped back, one hammering IP burns the
    # whole site's daily budget with rejected requests and this test fails.
    monkeypatch.setattr(settings, "CHAT_RATE_LIMIT", "1/minute")
    monkeypatch.setattr(settings, "CHAT_GLOBAL_RATE_LIMIT", "3/day")
    client()  # installs the dependency overrides on the shared app

    attacker = TestClient(app, client=("10.0.0.1", 50000))
    statuses = [
        attacker.post("/v1/chat", json={"message": "hi"}).status_code
        for _ in range(4)
    ]
    assert statuses == [200, 429, 429, 429]

    # The attacker consumed 1 of 3 global slots, not 4: others still get in.
    victim = TestClient(app, client=("10.0.0.2", 50000)).post(
        "/v1/chat", json={"message": "hi"}
    )
    assert victim.status_code == 200


def test_rate_limit_429_logs_which_layer_tripped(
    monkeypatch, captured_app_logs
):
    monkeypatch.setattr(settings, "CHAT_GLOBAL_RATE_LIMIT", "1/day")
    test_client = client()

    test_client.post("/v1/chat", json={"message": "hi"})
    response = test_client.post("/v1/chat", json={"message": "hi"})

    assert response.status_code == 429
    warnings = [
        line for line in captured_app_logs if "Rate limit exceeded" in line
    ]
    assert len(warnings) == 1
    # The limit string identifies the layer in the logs only — it must
    # never leak into the response body.
    assert "1 per 1 day" in warnings[0]
    assert "1 per 1 day" not in response.text


def test_catch_all_handler_returns_safe_500():
    app.dependency_overrides[get_rag_orchestrator] = lambda: (
        UnexpectedlyFailingOrchestrator()
    )
    app.dependency_overrides[require_internal_api_key] = lambda: None
    # raise_server_exceptions=False lets the registered handler produce the
    # response instead of the TestClient re-raising the exception.
    response = TestClient(app, raise_server_exceptions=False).post(
        "/v1/chat",
        json={"message": "How do I enrol?"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred. Please try again later.",
        }
    }
    assert "supersecret" not in response.text
