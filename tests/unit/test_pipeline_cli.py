import json
from unittest.mock import ANY, patch

import pytest

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
    mock_run_local_harvest.assert_called_once()


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
    mock_process_articles.assert_called_once()


@patch(
    "pipelines.orchestration.import_knowledge_base.run_local_import"
)
def test_import_knowledge_base_command(mock_run_local_import):
    mock_run_local_import.return_value = ImportResult(
        attempted_count=10,
        affected_count=8,
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
        mock_run_local_import.call_args.kwargs["checkpoint_key"]
        == "checkpoint.json"
    )
    assert mock_run_local_import.call_args.kwargs["reset_checkpoint"] is True


@patch(
    "pipelines.orchestration.wechat_pipeline.run_local_wechat_pipeline"
)
@patch("pipelines.loaders.postgres_pipeline_runs.PostgresPipelineRunLoader")
def test_run_wechat_pipeline_command(
    mock_pipeline_run_loader_class,
    mock_run_pipeline,
):
    mock_run_pipeline.return_value = WechatPipelineRunResult(
        run_id="run-123",
        harvested_count=12,
        transformed_count=9,
        skipped_count=2,
        dropped_count=1,
        attempted_import_count=9,
        affected_count=8,
        raw_output_location="raw/wechat/wechat_articles_all.json",
        processed_output_key="current/wechat_articles_processed.json",
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
    mock_pipeline_run_loader_class.assert_called_once_with(
        "postgresql://test:test@localhost:5432/testdb"
    )
    mock_run_pipeline.assert_called_once_with(
        ANY,
        database_url=(
            "postgresql://test:test@localhost:5432/testdb"
        ),
        batch_size=100,
        reset_import_checkpoint=True,
        pipeline_run_loader=(
            mock_pipeline_run_loader_class.return_value
        ),
        run_id=ANY,
    )


@patch(
    "pipelines.orchestration.import_knowledge_base.run_local_import"
)
def test_import_completion_line_carries_the_corpus_coordinates(
    mock_run_local_import,
    capsys,
):
    # In an ECS container the report file dies with the task; this JSON line
    # is the record that survives, so it has to carry every number the
    # operator copies out of it.
    mock_run_local_import.return_value = ImportResult(
        attempted_count=3,
        affected_count=0,
        corpus_sha256="ab" * 32,
        knowledge_base_rows=3,
        unique_record_count=3,
        rows_outside_corpus=0,
        skipped_by_checkpoint=False,
        report_key="reports/pipelines/import_knowledge_base_x.json",
    )

    exit_code = main(
        [
            "import-knowledge-base",
            "--database-url",
            "postgresql://importer:s3cret@db.internal:5432/rag_vectordb",
        ]
    )

    lines = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    completed = next(
        line for line in lines if line.get("event") == "command_completed"
    )
    assert exit_code == 0
    assert completed["corpus_sha256"] == "ab" * 32
    assert completed["knowledge_base_rows"] == 3
    assert completed["unique_record_count"] == 3
    assert completed["rows_outside_corpus"] == 0
    assert completed["skipped_by_checkpoint"] is False
    assert completed["report_key"] == (
        "reports/pipelines/import_knowledge_base_x.json"
    )
    assert completed["target_id"] == (
        "postgresql://db.internal:5432/rag_vectordb"
    )
    assert "s3cret" not in json.dumps(lines)
    # The report is named after the same run_id the log lines carry.
    assert (
        mock_run_local_import.call_args.kwargs["run_id"]
        == completed["run_id"]
    )


@patch(
    "pipelines.orchestration.import_knowledge_base.run_local_import"
)
def test_import_uses_the_url_settings_assembles(
    mock_run_local_import,
    monkeypatch,
):
    # An ECS task has no DATABASE_URL, only the DB_* parts Settings joins.
    from app.core.config import settings

    mock_run_local_import.return_value = ImportResult(
        attempted_count=0,
        affected_count=0,
    )
    monkeypatch.setattr(
        settings,
        "DATABASE_URL",
        "postgresql://migrator:pw@db.internal:5432/rag_vectordb",
    )

    assert main(["import-knowledge-base"]) == 0
    assert mock_run_local_import.call_args.kwargs["database_url"] == (
        "postgresql://migrator:pw@db.internal:5432/rag_vectordb"
    )


def test_import_without_any_database_url_is_a_usage_error(
    monkeypatch,
    capsys,
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL", None)

    with pytest.raises(SystemExit) as error:
        main(["import-knowledge-base"])

    assert error.value.code == 2
    assert "DB_HOST" in capsys.readouterr().err
