import json
import shutil
from datetime import datetime, timezone
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
    data_dir = Path(__file__).parent / ".tmp_wechat_pipeline"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir()

    try:
        with (
            patch(
                "pipelines.orchestration.wechat_pipeline.run_local_harvest",
                return_value=HarvestResult(
                    output_location=(
                        str(data_dir)
                        + "/raw/wechat/"
                        "wechat_articles_20260710T010203Z.json"
                    ),
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
                    affected_count=8,
                ),
            ) as import_records,
            patch(
                "pipelines.orchestration.wechat_pipeline.logger"
            ) as pipeline_logger,
        ):
            with patch(
                "pipelines.orchestration.wechat_pipeline.datetime"
            ) as fake_datetime:
                fake_datetime.now.return_value = datetime(
                    2026, 7, 10, 1, 2, 3, tzinfo=timezone.utc
                )
                fake_datetime.side_effect = (
                    lambda *args, **kwargs: datetime(*args, **kwargs)
                )
                result = run_local_wechat_pipeline(
                    DATABASE_URL,
                    data_dir=data_dir,
                    run_id="run-123",
                )
    finally:
        report_file = (
            data_dir
            / "reports"
            / "pipelines"
            / "wechat_pipeline_run-123.json"
        )
        report_payload = json.loads(
            report_file.read_text(encoding="utf-8")
        )
        shutil.rmtree(data_dir)

    raw_output_location = (
        str(data_dir)
        + "/raw/wechat/"
        "wechat_articles_20260710T010203Z.json"
    )
    expected_report_file = (
        data_dir
        / "reports"
        / "pipelines"
        / "wechat_pipeline_run-123.json"
    )
    assert report_payload["status"] == "completed"
    assert report_payload["pipeline"] == "wechat"
    assert report_payload["transformed_count"] == 9
    assert report_payload["affected_count"] == 8
    assert report_payload["raw_output_location"] == raw_output_location

    assert result == WechatPipelineRunResult(
        run_id="run-123",
        harvested_count=12,
        transformed_count=9,
        skipped_count=2,
        dropped_count=1,
        attempted_import_count=9,
        affected_count=8,
        raw_output_location=raw_output_location,
        processed_output_file=(
            data_dir / "current" / "wechat_articles_processed.json"
        ),
        report_file=expected_report_file,
    )
    assert result.rejected_count == 3
    harvest.assert_called_once_with(
        config=None,
        data_dir=data_dir,
        run_started_at=datetime(
            2026, 7, 10, 1, 2, 3, tzinfo=timezone.utc
        ),
    )
    transform.assert_called_once_with(
        input_file=data_dir / "current" / "wechat_articles_all.json",
        output_file=data_dir / "current" / "wechat_articles_processed.json",
        data_dir=data_dir,
        created_at=None,
        run_started_at=datetime(
            2026, 7, 10, 1, 2, 3, tzinfo=timezone.utc
        ),
    )
    import_records.assert_called_once_with(
        database_url=DATABASE_URL,
        input_file=data_dir / "current" / "wechat_articles_processed.json",
        model_name=None,
        model_revision=None,
        table_name=None,
        batch_size=100,
        checkpoint_file=None,
        reset_checkpoint=False,
    )
    completed_events = [
        call.kwargs["extra"]["stage"]
        for call in pipeline_logger.info.call_args_list
        if call.kwargs.get("extra", {}).get("event")
        == "stage_completed"
    ]
    assert completed_events == ["harvest", "transform", "import"]


def test_local_pipeline_writes_failure_report():
    data_dir = Path(__file__).parent / ".tmp_wechat_pipeline_failure"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir()

    try:
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
            patch(
                "pipelines.orchestration.wechat_pipeline.logger"
            ) as pipeline_logger,
            pytest.raises(ValueError, match="invalid raw data"),
        ):
            run_local_wechat_pipeline(
                DATABASE_URL,
                data_dir=data_dir,
                run_id="run-failure",
            )

        report_file = (
            data_dir
            / "reports"
            / "pipelines"
            / "wechat_pipeline_run-failure.json"
        )
        report_payload = json.loads(
            report_file.read_text(encoding="utf-8")
        )
    finally:
        shutil.rmtree(data_dir)

    assert report_payload["status"] == "failed"
    assert report_payload["error_type"] == "ValueError"
    assert report_payload["error_message"] == "invalid raw data"
    import_records.assert_not_called()
    assert (
        pipeline_logger.exception.call_args.kwargs["extra"]["stage"]
        == "transform"
    )

