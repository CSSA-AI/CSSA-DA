from pathlib import Path

from pipelines.shared.paths import (
    DEFAULT_IMPORT_CHECKPOINT_FILE,
    DEFAULT_KNOWLEDGE_BASE_INPUT,
    DEFAULT_PIPELINE_REPORTS_DIR,
    DEFAULT_WECHAT_CHECKPOINT_FILE,
    DEFAULT_WECHAT_TEMP_CHUNKS_DIR,
    import_checkpoint_file_for,
)


def test_default_pipeline_artifacts_use_production_data_layout():
    assert "data/current" in DEFAULT_KNOWLEDGE_BASE_INPUT.as_posix()
    assert "data/checkpoints" in DEFAULT_IMPORT_CHECKPOINT_FILE.as_posix()
    assert "data/checkpoints" in DEFAULT_WECHAT_CHECKPOINT_FILE.as_posix()
    assert "data/checkpoints" in DEFAULT_WECHAT_TEMP_CHUNKS_DIR.as_posix()
    assert "data/reports/pipelines" in DEFAULT_PIPELINE_REPORTS_DIR.as_posix()


def test_import_checkpoint_defaults_to_data_checkpoints_for_current_input():
    input_file = Path("example-data/current/wechat_articles_processed.json")

    assert import_checkpoint_file_for(input_file) == (
        Path("example-data")
        / "checkpoints"
        / "import_knowledge_base.json"
    )


def test_import_checkpoint_stays_near_custom_non_current_input():
    input_file = Path("example-data/custom/records.json")

    assert import_checkpoint_file_for(input_file) == (
        Path("example-data")
        / "custom"
        / "checkpoints"
        / "import_knowledge_base.json"
    )
