from datetime import datetime, timezone

from app.services import system_status


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
        return self.fetch_values.pop(0)


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def cursor(self):
        return self._cursor


def test_pipeline_metadata_reports_latest_run(monkeypatch):
    cursor = FakeCursor(
        [
            ("pipeline_runs",),
            (
                "wechat",
                "failed",
                datetime(2026, 7, 14, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 14, 2, tzinfo=timezone.utc),
                "data/reports/pipelines/wechat_pipeline_run-123.json",
                "ValueError",
                "invalid raw data",
            ),
        ]
    )
    monkeypatch.setattr(
        system_status.psycopg2,
        "connect",
        lambda database_url: FakeConnection(cursor),
    )

    status = system_status.get_pipeline_metadata_status(
        "postgresql://test"
    )

    assert status.reason is None
    assert status.latest_run is not None
    assert status.latest_run.status == "failed"
    assert status.latest_run.error_type == "ValueError"
    assert status.to_dict()["available"] is True


def test_pipeline_metadata_handles_missing_table(monkeypatch):
    cursor = FakeCursor([(None,)])
    monkeypatch.setattr(
        system_status.psycopg2,
        "connect",
        lambda database_url: FakeConnection(cursor),
    )

    status = system_status.get_pipeline_metadata_status(
        "postgresql://test"
    )

    assert status.latest_run is None
    assert status.reason == "pipeline_runs table does not exist"


def test_system_status_keeps_rag_readiness_separate_from_pipeline(
    monkeypatch,
):
    monkeypatch.setattr(
        system_status,
        "check_readiness",
        lambda database_url=None: system_status.ReadinessCheck(
            status="ready",
            database="ok",
            knowledge_base_rows=10,
            embedding_model="test-model",
            embedding_revision="revision-123",
        ),
    )
    monkeypatch.setattr(
        system_status,
        "get_pipeline_metadata_status",
        lambda database_url=None: system_status.PipelineMetadataStatus(
            latest_run=system_status.LatestPipelineRun(
                pipeline_name="wechat",
                status="failed",
                started_at="2026-07-14T01:00:00+00:00",
                finished_at="2026-07-14T02:00:00+00:00",
                report_path="report.json",
                error_type="ValueError",
                error_message="invalid raw data",
            )
        ),
    )

    status = system_status.get_system_status("postgresql://test")
    payload = status.to_dict()

    assert payload["rag_ready"] is True
    assert payload["readiness"]["status"] == "ready"
    assert payload["pipeline_metadata"]["latest_run"]["status"] == "failed"
