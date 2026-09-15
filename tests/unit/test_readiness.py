import pytest

from app.services import readiness
from app.services.rag.model_registry import ModelRegistryStatus


@pytest.fixture(autouse=True)
def ready_models(monkeypatch):
    monkeypatch.setattr(
        readiness.model_registry,
        "status",
        lambda: ModelRegistryStatus(
            embedding="ready",
            reranker="ready",
        ),
    )


class FakeCursor:
    def __init__(self, fetch_values):
        self.fetch_values = list(fetch_values)
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return (self.fetch_values.pop(0),)


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def cursor(self):
        return self._cursor


def test_check_readiness_reports_missing_database_url(monkeypatch):
    monkeypatch.setattr(readiness.settings, "DATABASE_URL", None)

    result = readiness.check_readiness()

    assert result.status == "not_ready"
    assert result.database == "missing"
    assert result.reason == "DATABASE_URL is not configured"


def test_check_readiness_reports_missing_knowledge_base_table(monkeypatch):
    cursor = FakeCursor([None])
    monkeypatch.setattr(
        readiness.psycopg2,
        "connect",
        lambda database_url, **kwargs: FakeConnection(cursor),
    )

    result = readiness.check_readiness("postgresql://test")

    assert result.status == "not_ready"
    assert result.database == "ok"
    assert result.knowledge_base_rows == 0
    assert result.reason == "knowledge_base table does not exist"


def test_check_readiness_reports_empty_matching_rows(monkeypatch):
    cursor = FakeCursor(["knowledge_base", 0])
    monkeypatch.setattr(
        readiness.psycopg2,
        "connect",
        lambda database_url, **kwargs: FakeConnection(cursor),
    )

    result = readiness.check_readiness("postgresql://test")

    assert result.status == "not_ready"
    assert result.database == "ok"
    assert result.knowledge_base_rows == 0
    assert result.reason == (
        "knowledge_base has no rows for the active embedding model/revision"
    )


def test_check_readiness_reports_ready_with_matching_rows(monkeypatch):
    cursor = FakeCursor(["knowledge_base", 12])
    monkeypatch.setattr(
        readiness.psycopg2,
        "connect",
        lambda database_url, **kwargs: FakeConnection(cursor),
    )

    result = readiness.check_readiness("postgresql://test")

    assert result.status == "ready"
    assert result.database == "ok"
    assert result.knowledge_base_rows == 12
    assert result.reason is None


def test_check_readiness_rejects_failed_models(monkeypatch):
    cursor = FakeCursor(["knowledge_base", 12])
    monkeypatch.setattr(
        readiness.psycopg2,
        "connect",
        lambda database_url, **kwargs: FakeConnection(cursor),
    )
    monkeypatch.setattr(
        readiness.model_registry,
        "status",
        lambda: ModelRegistryStatus(
            embedding="ready",
            reranker="failed",
        ),
    )

    result = readiness.check_readiness("postgresql://test")

    assert result.status == "not_ready"
    assert result.database == "ok"
    assert result.models.state == "failed"
    assert result.reason == "RAG models are not ready"


def test_check_readiness_reports_unavailable_database(monkeypatch, caplog):
    internal_error = "connection refused for internal-db.example:5432"
    monkeypatch.setattr(
        readiness.psycopg2,
        "connect",
        lambda database_url, **kwargs: (_ for _ in ()).throw(
            RuntimeError(internal_error)
        ),
    )

    result = readiness.check_readiness("postgresql://test")

    assert result.status == "not_ready"
    assert result.database == "unavailable"
    assert result.reason == "Database is unavailable"
    assert internal_error not in str(result.to_dict())
    assert "Database readiness check failed" in caplog.text
    assert internal_error in caplog.text


def test_check_readiness_passes_probe_timeouts_to_postgres(monkeypatch):
    cursor = FakeCursor([None])
    connect_arguments = {}

    def connect(database_url, **kwargs):
        connect_arguments.update(kwargs)
        return FakeConnection(cursor)

    monkeypatch.setattr(readiness.psycopg2, "connect", connect)

    readiness.check_readiness("postgresql://test")

    pgvector_config = readiness.rag_config["pgvector"]
    assert connect_arguments == {
        "connect_timeout": pgvector_config["probe_connect_timeout_seconds"],
        "options": (
            "-c statement_timeout="
            f"{pgvector_config['probe_statement_timeout_milliseconds']}"
        ),
    }
