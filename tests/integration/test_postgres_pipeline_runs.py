import os
from datetime import datetime, timezone

import psycopg2
import pytest

from pipelines.loaders.postgres_pipeline_runs import (
    PipelineRunRecord,
    upsert_pipeline_run,
)


pytestmark = pytest.mark.integration

if os.getenv("RUN_INTEGRATION_TESTS") != "1":
    pytest.skip("skip integration tests by default", allow_module_level=True)


def test_pipeline_run_can_be_inserted_and_updated(test_database_url):
    started_at = datetime(2026, 7, 13, tzinfo=timezone.utc)

    first_affected = upsert_pipeline_run(
        test_database_url,
        PipelineRunRecord(
            id="run-123",
            pipeline_name="wechat",
            status="started",
            started_at=started_at,
            input_path="data/current/wechat_articles_all.json",
        ),
    )
    second_affected = upsert_pipeline_run(
        test_database_url,
        PipelineRunRecord(
            id="run-123",
            pipeline_name="wechat",
            status="completed",
            started_at=started_at,
            finished_at=datetime(2026, 7, 13, 1, tzinfo=timezone.utc),
            input_path="data/current/wechat_articles_all.json",
            output_path="data/current/wechat_articles_processed.json",
            report_path=(
                "data/reports/pipelines/wechat_pipeline_run-123.json"
            ),
            record_count=9,
            affected_count=8,
        ),
    )

    with psycopg2.connect(test_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, output_path, report_path, record_count,
                       affected_count
                FROM pipeline_runs
                WHERE id = 'run-123';
                """
            )
            stored = cursor.fetchone()

    assert first_affected == 1
    assert second_affected == 1
    assert stored == (
        "completed",
        "data/current/wechat_articles_processed.json",
        "data/reports/pipelines/wechat_pipeline_run-123.json",
        9,
        8,
    )
