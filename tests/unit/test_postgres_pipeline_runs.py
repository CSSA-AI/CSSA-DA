from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from pipelines.loaders.postgres_pipeline_runs import (
    PipelineRunRecord,
    PostgresPipelineRunLoader,
)


DATABASE_URL = "postgresql://test:test@localhost:5432/testdb"


def _record(status: str = "started") -> PipelineRunRecord:
    return PipelineRunRecord(
        id="run-123",
        pipeline_name="wechat",
        status=status,
        started_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
    )


def test_loader_requires_database_url():
    with pytest.raises(ValueError, match="database_url is required"):
        PostgresPipelineRunLoader("")


def test_loader_rejects_unknown_status():
    loader = PostgresPipelineRunLoader(DATABASE_URL)

    with pytest.raises(ValueError, match="status must be one of"):
        loader.upsert_run(_record("unknown"))


def test_loader_rejects_finished_before_started():
    loader = PostgresPipelineRunLoader(DATABASE_URL)
    record = PipelineRunRecord(
        id="run-123",
        pipeline_name="wechat",
        status="completed",
        started_at=datetime(2026, 7, 13, 2, tzinfo=timezone.utc),
        finished_at=datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
    )

    with pytest.raises(
        ValueError,
        match="finished_at cannot be before started_at",
    ):
        loader.upsert_run(record)


@patch("pipelines.loaders.postgres_pipeline_runs.psycopg2.connect")
def test_loader_upserts_pipeline_run(mock_connect):
    connection = MagicMock()
    cursor = MagicMock()
    cursor.rowcount = 1
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    mock_connect.return_value = connection
    loader = PostgresPipelineRunLoader(DATABASE_URL)

    affected = loader.upsert_run(
        PipelineRunRecord(
            id="run-123",
            pipeline_name="wechat",
            status="completed",
            started_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
            finished_at=datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
            input_path="data/current/wechat_articles_all.json",
            output_path="data/current/wechat_articles_processed.json",
            report_path="data/reports/pipelines/wechat_pipeline_run-123.json",
            record_count=9,
            affected_count=8,
        )
    )

    assert affected == 1
    mock_connect.assert_called_once_with(DATABASE_URL)
    cursor.execute.assert_called_once()
    assert "ON CONFLICT (id) DO UPDATE" in cursor.execute.call_args.args[0]
    connection.commit.assert_called_once()
