from pathlib import Path
from unittest.mock import patch

import pytest

from pipelines.ingestion.wechat import HarvestResult
from pipelines.orchestration.import_knowledge_base import ImportResult
from pipelines.orchestration.wechat_pipeline import (
    WechatPipelineRunResult,
    run_local_wechat_pipeline,
)
from pipelines.transform.wechat_articles import (
    WechatTransformResult,
    WechatTransformStats,
)


DATABASE_URL = "postgresql://test:test@localhost:5432/testdb"


def _transform_result():
    return WechatTransformResult(
        records=[{"question_text": "Question"}],
        stats=WechatTransformStats(
            input_count=12,
            skipped_count=2,
            dropped_count=1,
            output_count=9,
            original_char_count=1000,
            cleaned_char_count=800,
        ),
    )


def test_local_pipeline_runs_stages_and_returns_report():
    data_dir = Path("test-data")

    with (
        patch(
            "pipelines.orchestration.wechat_pipeline.run_local_harvest",
            return_value=HarvestResult(
                output_location="test-data/wechat_articles_all.json",
                articles_written=12,
                total_saved=12,
                valid_count=10,
            ),
        ) as harvest,
        patch(
            "pipelines.orchestration.wechat_pipeline.run_local_transform",
            return_value=_transform_result(),
        ) as transform,
        patch(
            "pipelines.orchestration.wechat_pipeline.run_local_import",
            return_value=ImportResult(
                attempted_count=9,
                inserted_count=8,
            ),
        ) as import_records,
    ):
        result = run_local_wechat_pipeline(
            DATABASE_URL,
            data_dir=data_dir,
        )

    assert result == WechatPipelineRunResult(
        harvested_count=12,
        transformed_count=9,
        skipped_count=2,
        dropped_count=1,
        attempted_import_count=9,
        inserted_count=8,
        raw_output_location="test-data/wechat_articles_all.json",
        processed_output_file=(
            data_dir / "wechat_articles_processed.json"
        ),
    )
    assert result.rejected_count == 3
    harvest.assert_called_once_with(config=None, data_dir=data_dir)
    transform.assert_called_once_with(
        input_file=data_dir / "wechat_articles_all.json",
        output_file=data_dir / "wechat_articles_processed.json",
        created_at=None,
    )
    import_records.assert_called_once_with(
        database_url=DATABASE_URL,
        input_file=data_dir / "wechat_articles_processed.json",
        model_name=None,
        table_name=None,
        batch_size=100,
    )


def test_local_pipeline_stops_when_transformation_fails():
    with (
        patch(
            "pipelines.orchestration.wechat_pipeline.run_local_harvest",
            return_value=HarvestResult(
                output_location="raw.json",
                articles_written=1,
                total_saved=1,
                valid_count=1,
            ),
        ),
        patch(
            "pipelines.orchestration.wechat_pipeline.run_local_transform",
            side_effect=ValueError("invalid raw data"),
        ),
        patch(
            "pipelines.orchestration.wechat_pipeline.run_local_import"
        ) as import_records,
        pytest.raises(ValueError, match="invalid raw data"),
    ):
        run_local_wechat_pipeline(DATABASE_URL)

    import_records.assert_not_called()
