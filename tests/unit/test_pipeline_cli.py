from pathlib import Path
from unittest.mock import ANY, patch

from pipelines.cli import main
from pipelines.ingestion.wechat import HarvestResult
from pipelines.orchestration.import_knowledge_base import ImportResult
from pipelines.orchestration.wechat_pipeline import (
    WechatPipelineRunResult,
)
from pipelines.transform.wechat_articles import (
    WechatTransformResult,
    WechatTransformStats,
)


@patch("pipelines.orchestration.harvest_wechat.run_local_harvest")
def test_harvest_wechat_command(mock_run_local_harvest):
    mock_run_local_harvest.return_value = HarvestResult(
        output_location="data/wechat_articles_all.json",
        articles_written=10,
        total_saved=10,
        valid_count=8,
    )

    exit_code = main(["harvest-wechat"])

    assert exit_code == 0
    mock_run_local_harvest.assert_called_once_with()


@patch(
    "pipelines.orchestration.transform_wechat.run_local_transform"
)
def test_transform_wechat_command(mock_process_articles):
    mock_process_articles.return_value = WechatTransformResult(
        records=[],
        stats=WechatTransformStats(
            input_count=0,
            skipped_count=0,
            dropped_count=0,
            output_count=0,
            original_char_count=0,
            cleaned_char_count=0,
        ),
    )

    exit_code = main(["transform-wechat"])

    assert exit_code == 0
    mock_process_articles.assert_called_once_with()


@patch(
    "pipelines.orchestration.import_knowledge_base.run_local_import"
)
def test_import_knowledge_base_command(mock_run_local_import):
    mock_run_local_import.return_value = ImportResult(
        attempted_count=10,
        inserted_count=8,
    )

    exit_code = main(
        [
            "import-knowledge-base",
            "--database-url",
            "postgresql://test:test@localhost:5432/testdb",
            "--limit",
            "10",
            "--checkpoint-file",
            "checkpoint.json",
            "--reset-checkpoint",
        ]
    )

    assert exit_code == 0
    assert (
        mock_run_local_import.call_args.kwargs["checkpoint_file"]
        == Path("checkpoint.json")
    )
    assert mock_run_local_import.call_args.kwargs["reset_checkpoint"] is True


@patch(
    "pipelines.orchestration.wechat_pipeline.run_local_wechat_pipeline"
)
def test_run_wechat_pipeline_command(mock_run_pipeline):
    mock_run_pipeline.return_value = WechatPipelineRunResult(
        run_id="run-123",
        harvested_count=12,
        transformed_count=9,
        skipped_count=2,
        dropped_count=1,
        attempted_import_count=9,
        inserted_count=8,
        raw_output_location="data/wechat_articles_all.json",
        processed_output_file=Path(
            "data/wechat_articles_processed.json"
        ),
    )

    exit_code = main(
        [
            "run-wechat-pipeline",
            "--database-url",
            "postgresql://test:test@localhost:5432/testdb",
            "--reset-import-checkpoint",
        ]
    )

    assert exit_code == 0
    mock_run_pipeline.assert_called_once_with(
        database_url=(
            "postgresql://test:test@localhost:5432/testdb"
        ),
        batch_size=100,
        reset_import_checkpoint=True,
        run_id=ANY,
    )
