from pipelines.shared.paths import (
    DEFAULT_KNOWLEDGE_BASE_INPUT_KEY,
    IMPORT_CHECKPOINT_KEY,
    PIPELINE_REPORTS_PREFIX,
    WECHAT_CHECKPOINT_KEY,
    WECHAT_TEMP_CHUNKS_PREFIX,
)


def test_default_pipeline_artifacts_use_production_data_layout():
    assert DEFAULT_KNOWLEDGE_BASE_INPUT_KEY == (
        "current/wechat_articles_processed.json"
    )
    assert IMPORT_CHECKPOINT_KEY == "checkpoints/import_knowledge_base.json"
    assert WECHAT_CHECKPOINT_KEY == "checkpoints/wechat_scraper_state.json"
    assert WECHAT_TEMP_CHUNKS_PREFIX == "checkpoints/wechat_temp_chunks"
    assert PIPELINE_REPORTS_PREFIX == "reports/pipelines"
