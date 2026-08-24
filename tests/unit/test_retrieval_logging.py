"""End-to-end guards for the CSS-15 retrieval logging contract.

Two of the issue's acceptance criteria cannot be checked from a unit test
of the adapter alone, because they are properties of a whole request:

1. the stage logs and the access log carry the *same* `request_id`, and
2. no user content reaches the formatted output.

Both hold today only because `RequestContextMiddleware` binds a ContextVar
that `AppJsonLogFormatter` reads back out. Nothing in the adapter's own
tests would notice if that link broke -- if `/v1/chat` became `async def`
with the pipeline handed to an executor, or if `bind_request_id` moved,
the logs would keep being emitted and would silently stop being joinable.

These tests assert on the *formatted JSON* rather than on LogRecord
attributes, so they cover the formatter and its STRUCTURED_FIELDS
whitelist too.
"""

import io
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_rag_orchestrator, require_internal_api_key
from app.core.logging import AppJsonLogFormatter
from app.core.middleware import REQUEST_ID_HEADER
from app.main import app
from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.orchestrator import RAGOrchestrator

QUERY_TEXT = "how do I apply for oshc"
ARTICLE_TEXT = "OSHC application steps, in full."
ANSWER_TEXT = "Apply through your provider."


def _result(doc_id: str, score: float, rank: int) -> SearchResult:
    return SearchResult(
        article=Article(id=doc_id, text=ARTICLE_TEXT, questions=["q"]),
        score=score,
        rank=rank,
    )


class StubRetriever:
    def search(self, query, **kwargs):
        return [_result("wx_a", 0.9, 1), _result("wx_b", 0.8, 2)]


class StubReranker:
    def rerank(self, query, search_results, **kwargs):
        # Deliberately a different order and length from retrieval, so the
        # two stage lines are distinguishable in the output.
        return [_result("wx_b", 0.95, 1)]


class StubGenerator:
    def generate_text(self, query, search_results, chat_history=None):
        return ANSWER_TEXT


@pytest.fixture
def log_buffer():
    """Point the `app` logger at a buffer using the real JSON formatter."""
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(AppJsonLogFormatter())

    app_logger = logging.getLogger("app")
    original_handlers = app_logger.handlers[:]
    original_level = app_logger.level
    app_logger.handlers = [handler]
    app_logger.setLevel(logging.INFO)
    try:
        yield buffer
    finally:
        app_logger.handlers = original_handlers
        app_logger.setLevel(original_level)


@pytest.fixture
def chat_request(log_buffer):
    """Run one real `/v1/chat` through the real orchestrator and chain."""
    orchestrator = RAGOrchestrator(
        retriever=StubRetriever(),
        reranker=StubReranker(),
        generator=StubGenerator(),
    )
    app.dependency_overrides[get_rag_orchestrator] = lambda: orchestrator
    app.dependency_overrides[require_internal_api_key] = lambda: None
    try:
        # No `with` on the client: the lifespan would preload the real
        # cross-encoder, which this test has no use for.
        response = TestClient(app).post(
            "/v1/chat",
            json={"message": QUERY_TEXT},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    return response, log_buffer.getvalue()


def _json_lines(raw: str):
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def test_both_stage_logs_are_emitted_for_one_request(chat_request):
    _, raw = chat_request

    by_stage = {
        record["stage"]: record
        for record in _json_lines(raw)
        if record.get("stage")
    }

    assert by_stage["retrieve"]["results"] == [
        {"doc_id": "wx_a", "score": 0.9, "rank": 1},
        {"doc_id": "wx_b", "score": 0.8, "rank": 2},
    ]
    assert by_stage["rerank"]["results"] == [
        {"doc_id": "wx_b", "score": 0.95, "rank": 1},
    ]


def test_stage_logs_share_the_request_id_with_the_access_log(chat_request):
    response, raw = chat_request

    header_id = response.headers[REQUEST_ID_HEADER.decode()]
    records = _json_lines(raw)

    # request_id is the ONLY join key back to the query and answer, so a
    # stage line that carries a different id -- or none -- is unusable.
    assert {record.get("request_id") for record in records} == {header_id}

    stages = {record.get("stage") for record in records}
    assert {"retrieve", "rerank"} <= stages
    # The access log line is in the same set, which is what makes the
    # stage logs joinable to latency and status code.
    assert any(record.get("method") == "POST" for record in records)


def test_no_user_content_reaches_the_formatted_output(chat_request):
    _, raw = chat_request

    assert QUERY_TEXT not in raw
    assert ARTICLE_TEXT not in raw
    assert ANSWER_TEXT not in raw
