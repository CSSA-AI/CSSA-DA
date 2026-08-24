import logging

import pytest

from app.core.config import rag_config
from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services import chat_interactions
from app.services.chat_interactions import (
    ChatInteractionRecord,
    build_chat_interaction_record,
    build_config_fingerprint,
    build_retrieved,
    prompt_version,
    record_chat_interaction,
    schedule_chat_interaction,
)


def make_source(doc_id: str, score: float, rank: int) -> SearchResult:
    return SearchResult(
        article=Article(id=doc_id, text="content", source="test"),
        score=score,
        rank=rank,
    )


class RecordingBackgroundTasks:
    """Stand-in for fastapi.BackgroundTasks that just captures the call."""

    def __init__(self):
        self.tasks = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append((func, args, kwargs))


@pytest.fixture(autouse=True)
def clear_prompt_version_cache():
    prompt_version.cache_clear()
    yield
    prompt_version.cache_clear()


# --- config fingerprint -----------------------------------------------------


def test_fingerprint_carries_every_coordinate():
    fingerprint = build_config_fingerprint()

    # Missing any one of these is what makes a batch of rows uncomparable
    # after a model swap, so the set itself is the contract.
    assert set(fingerprint) == {
        "embedding_model",
        "embedding_revision",
        "reranker_model",
        "reranker_revision",
        "generator_model",
        "top_k",
        "rerank_top_k",
        "prompt_version",
        "corpus_sha256",
        "git_sha",
    }
    assert (
        fingerprint["embedding_model"]
        == rag_config["retriever"]["embedding_model"]
    )
    assert (
        fingerprint["reranker_revision"]
        == rag_config["reranker"]["model_revision"]
    )
    assert (
        fingerprint["generator_model"]
        == rag_config["generator"]["model_name"]
    )


def test_fingerprint_defaults_to_configured_top_k():
    fingerprint = build_config_fingerprint()

    assert fingerprint["top_k"] == rag_config["retriever"]["top_k"]
    assert fingerprint["rerank_top_k"] == rag_config["reranker"]["top_k"]


def test_fingerprint_records_the_per_request_override():
    """The config that actually ran, not the one that would have."""
    fingerprint = build_config_fingerprint(top_k=42, rerank_top_k=7)

    assert fingerprint["top_k"] == 42
    assert fingerprint["rerank_top_k"] == 7


def test_fingerprint_reads_deploy_time_coordinates(monkeypatch):
    monkeypatch.setattr(chat_interactions.settings, "GIT_SHA", "abc123")
    monkeypatch.setattr(
        chat_interactions.settings,
        "CORPUS_SHA256",
        "deadbeef",
    )

    fingerprint = build_config_fingerprint()

    assert fingerprint["git_sha"] == "abc123"
    assert fingerprint["corpus_sha256"] == "deadbeef"


def test_unset_deploy_coordinates_are_null_not_missing(monkeypatch):
    monkeypatch.setattr(chat_interactions.settings, "GIT_SHA", None)
    monkeypatch.setattr(chat_interactions.settings, "CORPUS_SHA256", None)

    fingerprint = build_config_fingerprint()

    assert fingerprint["git_sha"] is None
    assert fingerprint["corpus_sha256"] is None


def test_prompt_version_tracks_the_prompt_text(monkeypatch):
    """A derived version cannot drift the way a hand-bumped one does."""
    before = prompt_version()

    prompt_version.cache_clear()
    monkeypatch.setitem(
        rag_config["generator"],
        "system_prompt",
        "a different prompt",
    )
    after = prompt_version()

    assert before != after
    assert after.startswith("sha256:")


# --- retrieved --------------------------------------------------------------


def test_retrieved_records_doc_id_score_and_rank():
    retrieved = build_retrieved(
        [make_source("doc-a", 0.9, 1), make_source("doc-b", 0.4, 2)]
    )

    assert retrieved == [
        {"doc_id": "doc-a", "score": 0.9, "rank": 1},
        {"doc_id": "doc-b", "score": 0.4, "rank": 2},
    ]


def test_retrieved_is_empty_when_nothing_was_retrieved():
    assert build_retrieved([]) == []


# --- building the record ----------------------------------------------------


def test_record_uses_the_bound_request_id():
    from app.core.logging import bind_request_id

    with bind_request_id("req-42"):
        record = build_chat_interaction_record(
            query="how do I apply?",
            answer="via the portal",
            sources=[make_source("doc-a", 0.9, 1)],
        )

    assert record.request_id == "req-42"
    assert record.query == "how do I apply?"
    assert record.answer == "via the portal"
    assert record.retrieved == [{"doc_id": "doc-a", "score": 0.9, "rank": 1}]
    assert record.config["prompt_version"].startswith("sha256:")


# --- writing ----------------------------------------------------------------


def test_write_failure_never_raises_and_logs_the_full_query(
    monkeypatch,
    caplog,
):
    """A dead database must cost the user nothing and lose no query."""

    def explode(*args, **kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(chat_interactions.psycopg2, "connect", explode)

    record = ChatInteractionRecord(
        request_id="req-1",
        query="a query that must survive the outage",
        answer="an answer",
        retrieved=[{"doc_id": "doc-a", "score": 0.9, "rank": 1}],
        config={"git_sha": "abc123"},
    )

    with caplog.at_level(logging.ERROR):
        record_chat_interaction(record, database_url="postgresql://example")

    payload = caplog.records[-1].chat_interaction
    assert payload["query"] == "a query that must survive the outage"
    assert payload["answer"] == "an answer"
    assert payload["request_id"] == "req-1"
    assert payload["config"] == {"git_sha": "abc123"}


def test_missing_database_url_is_logged_not_raised(caplog):
    record = ChatInteractionRecord(request_id="req-1", query="a query")

    with caplog.at_level(logging.ERROR):
        record_chat_interaction(record, database_url="")

    assert "Failed to record chat interaction" in caplog.text
    assert caplog.records[-1].chat_interaction["query"] == "a query"


def test_duplicate_request_id_warns_instead_of_dropping_silently(
    monkeypatch,
    caplog,
):
    """ON CONFLICT DO NOTHING must not turn a lost query into silence."""

    class FakeCursor:
        rowcount = 0

        def execute(self, *args, **kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class FakeConnection:
        closed_explicitly = False

        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

        def close(self):
            type(self).closed_explicitly = True

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        chat_interactions.psycopg2,
        "connect",
        lambda *args, **kwargs: FakeConnection(),
    )

    record = ChatInteractionRecord(request_id="reused", query="a query")

    with caplog.at_level(logging.WARNING):
        record_chat_interaction(record, database_url="postgresql://example")

    assert "Duplicate chat interaction request_id" in caplog.text
    assert caplog.records[-1].chat_interaction["query"] == "a query"
    # Runs once per answered request, so the connection must not be left for
    # the garbage collector to reclaim.
    assert FakeConnection.closed_explicitly is True


# --- scheduling -------------------------------------------------------------


def test_scheduling_queues_exactly_one_write():
    background_tasks = RecordingBackgroundTasks()

    schedule_chat_interaction(
        background_tasks,
        query="a query",
        answer="an answer",
        sources=[make_source("doc-a", 0.9, 1)],
    )

    assert len(background_tasks.tasks) == 1
    func, args, _ = background_tasks.tasks[0]
    assert func is record_chat_interaction
    assert args[0].query == "a query"


def test_scheduling_failure_cannot_break_a_successful_request(
    monkeypatch,
    caplog,
):
    """Building the record is inside the request; it must not 500 it."""

    def explode(**kwargs):
        raise RuntimeError("cannot build record")

    monkeypatch.setattr(
        chat_interactions,
        "build_chat_interaction_record",
        explode,
    )
    background_tasks = RecordingBackgroundTasks()

    with caplog.at_level(logging.ERROR):
        schedule_chat_interaction(
            background_tasks,
            query="a query",
            answer="an answer",
            sources=[],
        )

    assert background_tasks.tasks == []
    assert "Failed to schedule chat interaction recording" in caplog.text
