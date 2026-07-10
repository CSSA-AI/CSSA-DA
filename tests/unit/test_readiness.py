from app.services import readiness


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
        lambda database_url: FakeConnection(cursor),
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
        lambda database_url: FakeConnection(cursor),
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
        lambda database_url: FakeConnection(cursor),
    )

    result = readiness.check_readiness("postgresql://test")

    assert result.status == "ready"
    assert result.database == "ok"
    assert result.knowledge_base_rows == 12
    assert result.reason is None


def test_check_readiness_reports_unavailable_database(monkeypatch):
    monkeypatch.setattr(
        readiness.psycopg2,
        "connect",
        lambda database_url: (_ for _ in ()).throw(
            RuntimeError("connection refused")
        ),
    )

    result = readiness.check_readiness("postgresql://test")

    assert result.status == "not_ready"
    assert result.database == "unavailable"
    assert result.reason == "connection refused"
