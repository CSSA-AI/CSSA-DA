from datetime import datetime, timezone

from ops import db_status


class FakeCursor:
    def __init__(self, fetch_values=None, fetchall_values=None):
        self.fetch_values = list(fetch_values or [])
        self.fetchall_values = list(fetchall_values or [])
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return (self.fetch_values.pop(0),)

    def fetchall(self):
        return self.fetchall_values.pop(0)


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def cursor(self):
        return self._cursor


def test_status_reports_missing_database_url(monkeypatch):
    monkeypatch.setattr(db_status.settings, "DATABASE_URL", None)

    status = db_status.get_knowledge_base_status()

    assert status.database == "missing"
    assert status.table_exists is False
    assert status.reason == "DATABASE_URL is not configured"


def test_status_reports_missing_table(monkeypatch):
    cursor = FakeCursor([None])
    monkeypatch.setattr(
        db_status.psycopg2,
        "connect",
        lambda database_url: FakeConnection(cursor),
    )

    status = db_status.get_knowledge_base_status("postgresql://test")

    assert status.database == "ok"
    assert status.table_exists is False
    assert status.reason == "knowledge_base table does not exist"


def test_status_summarizes_knowledge_base(monkeypatch):
    cursor = FakeCursor(
        [
            "knowledge_base",
            12,
            10,
            datetime(2026, 7, 10, tzinfo=timezone.utc),
        ],
        [
            [
                ("model-a", "revision-a", 10),
                ("model-b", "revision-b", 2),
            ]
        ],
    )
    monkeypatch.setattr(
        db_status.psycopg2,
        "connect",
        lambda database_url: FakeConnection(cursor),
    )

    status = db_status.get_knowledge_base_status("postgresql://test")

    assert status.database == "ok"
    assert status.table_exists is True
    assert status.total_rows == 12
    assert status.active_rows == 10
    assert status.latest_created_at == "2026-07-10T00:00:00+00:00"
    assert status.embedding_groups[0].embedding_model == "model-a"
    assert status.embedding_groups[0].embedding_revision == "revision-a"
    assert status.embedding_groups[0].row_count == 10


def test_status_reports_unavailable_database(monkeypatch):
    monkeypatch.setattr(
        db_status.psycopg2,
        "connect",
        lambda database_url: (_ for _ in ()).throw(
            RuntimeError("connection refused")
        ),
    )

    status = db_status.get_knowledge_base_status("postgresql://test")

    assert status.database == "unavailable"
    assert status.table_exists is False
    assert status.reason == "connection refused"
