import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_rag_orchestrator, require_caller
from app.core.config import settings
from app.main import app


class StubOrchestrator:
    def run(self, query, **kwargs):
        return (f"Answer for: {query}", [])


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _chat_body(message_len: int) -> bytes:
    return json.dumps({"message": "x" * message_len}).encode("utf-8")


def test_chat_rejects_an_oversized_body_before_auth_runs(monkeypatch):
    # No API key configured or provided, and require_caller is NOT
    # overridden: if the body-size check ran after auth (or not at all), this
    # would come back 401/503, not 413.
    monkeypatch.setattr(settings, "MAX_REQUEST_BODY_BYTES", 100)

    response = TestClient(app).post(
        "/v1/chat",
        json={"message": "x" * 1_000},
    )

    assert response.status_code == 413
    assert response.json() == {
        "error": {
            "code": "payload_too_large",
            "message": "Request body exceeds the maximum allowed size.",
        }
    }


def test_chat_allows_an_under_limit_body_through_to_auth(monkeypatch):
    monkeypatch.setattr(settings, "MAX_REQUEST_BODY_BYTES", 100_000)

    response = TestClient(app).post(
        "/v1/chat",
        json={"message": "hi"},
    )

    # Proves the request passed the body-size layer: it was rejected further
    # down the stack (by auth), not short-circuited with 413.
    assert response.status_code != 413


def test_chat_accepts_a_body_at_exactly_the_content_length_limit(monkeypatch):
    body = _chat_body(50)
    monkeypatch.setattr(settings, "MAX_REQUEST_BODY_BYTES", len(body))

    response = TestClient(app).post(
        "/v1/chat",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code != 413


def test_chat_rejects_a_body_one_byte_over_the_content_length_limit(monkeypatch):
    body = _chat_body(50)
    monkeypatch.setattr(settings, "MAX_REQUEST_BODY_BYTES", len(body) - 1)

    response = TestClient(app).post(
        "/v1/chat",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413


def test_chat_rejects_an_oversized_chunked_body_with_no_content_length(monkeypatch):
    # A generator body makes httpx use chunked transfer encoding, so no
    # Content-Length header reaches the middleware — this exercises the
    # streamed byte-counting path, not the upfront header check.
    monkeypatch.setattr(settings, "MAX_REQUEST_BODY_BYTES", 100)

    def chunks():
        for _ in range(20):
            yield b"x" * 10  # 200 bytes total, over the 100-byte limit

    response = TestClient(app).post("/v1/chat", content=chunks())

    assert response.status_code == 413
    assert response.json() == {
        "error": {
            "code": "payload_too_large",
            "message": "Request body exceeds the maximum allowed size.",
        }
    }


def test_chat_accepts_a_chunked_body_under_the_limit(monkeypatch):
    monkeypatch.setattr(settings, "MAX_REQUEST_BODY_BYTES", 100_000)
    app.dependency_overrides[require_caller] = lambda: None
    app.dependency_overrides[get_rag_orchestrator] = lambda: StubOrchestrator()

    def chunks():
        yield json.dumps({"message": "How do I enrol?"}).encode("utf-8")

    response = TestClient(app).post("/v1/chat", content=chunks())

    assert response.status_code != 413
