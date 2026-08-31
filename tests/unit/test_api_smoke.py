from ops.smoke_test_api import smoke_test_api


def test_smoke_test_api_checks_health_and_chat(monkeypatch):
    calls = []

    def fake_request_json(
        method,
        url,
        *,
        payload=None,
        headers=None,
        timeout=30,
    ):
        calls.append((method, url, payload, headers, timeout))
        if url.endswith("/health"):
            return {"status": "ok"}
        if url.endswith("/ready"):
            return {"status": "ready"}
        return {
            "answer": "Here is an answer.",
            "sources": [{"article": {"link": "https://example.com"}}],
        }

    monkeypatch.setattr(
        "ops.smoke_test_api.request_json",
        fake_request_json,
    )

    exit_code = smoke_test_api(
        "http://localhost:8000/",
        message="墨尔本 校招",
        top_k=2,
        rerank_top_k=1,
        api_key="test-chat-key",
        timeout=5,
    )

    assert exit_code == 0
    assert calls == [
        ("GET", "http://localhost:8000/health", None, None, 5),
        ("GET", "http://localhost:8000/ready", None, None, 5),
        (
            "POST",
            "http://localhost:8000/v1/chat",
            {
                "message": "墨尔本 校招",
                "top_k": 2,
                "rerank_top_k": 1,
            },
            {"X-API-Key": "test-chat-key"},
            5,
        ),
    ]


def test_smoke_test_api_can_check_health_only(monkeypatch):
    calls = []

    def fake_request_json(
        method, url, *, payload=None, headers=None, timeout=30
    ):
        calls.append((method, url))
        return {"status": "ok"}

    monkeypatch.setattr(
        "ops.smoke_test_api.request_json",
        fake_request_json,
    )

    exit_code = smoke_test_api(
        "http://localhost:8000",
        message="ignored",
        health_only=True,
    )

    assert exit_code == 0
    assert calls == [("GET", "http://localhost:8000/health")]


def test_smoke_test_api_can_check_ready_only(monkeypatch):
    calls = []

    def fake_request_json(
        method, url, *, payload=None, headers=None, timeout=30
    ):
        calls.append((method, url))
        if url.endswith("/health"):
            return {"status": "ok"}
        return {"status": "ready"}

    monkeypatch.setattr(
        "ops.smoke_test_api.request_json",
        fake_request_json,
    )

    exit_code = smoke_test_api(
        "http://localhost:8000",
        message="ignored",
        ready_only=True,
    )

    assert exit_code == 0
    assert calls == [
        ("GET", "http://localhost:8000/health"),
        ("GET", "http://localhost:8000/ready"),
    ]


def test_smoke_test_api_fails_when_not_ready(monkeypatch):
    def fake_request_json(
        method, url, *, payload=None, headers=None, timeout=30
    ):
        if url.endswith("/health"):
            return {"status": "ok"}
        return {"status": "not_ready", "reason": "no rows"}

    monkeypatch.setattr(
        "ops.smoke_test_api.request_json",
        fake_request_json,
    )

    exit_code = smoke_test_api(
        "http://localhost:8000",
        message="墨尔本 校招",
    )

    assert exit_code == 1


def test_smoke_test_api_fails_without_sources(monkeypatch):
    def fake_request_json(
        method, url, *, payload=None, headers=None, timeout=30
    ):
        if url.endswith("/health"):
            return {"status": "ok"}
        if url.endswith("/ready"):
            return {"status": "ready"}
        return {"answer": "No sources.", "sources": []}

    monkeypatch.setattr(
        "ops.smoke_test_api.request_json",
        fake_request_json,
    )

    exit_code = smoke_test_api(
        "http://localhost:8000",
        message="墨尔本 校招",
    )

    assert exit_code == 1
