from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_RAW_DATA_DIR = DEFAULT_DATA_DIR / "raw"
DEFAULT_PROCESSED_DATA_DIR = DEFAULT_DATA_DIR / "processed"
DEFAULT_CURRENT_DATA_DIR = DEFAULT_DATA_DIR / "current"
DEFAULT_CHECKPOINT_DATA_DIR = DEFAULT_DATA_DIR / "checkpoints"
DEFAULT_REPORTS_DATA_DIR = DEFAULT_DATA_DIR / "reports"
DEFAULT_WECHAT_RAW_DIR = DEFAULT_RAW_DATA_DIR / "wechat"
DEFAULT_KNOWLEDGE_BASE_PROCESSED_DIR = (
    DEFAULT_PROCESSED_DATA_DIR / "knowledge_base"
)
DEFAULT_WECHAT_CHECKPOINT_FILE = (
    DEFAULT_CHECKPOINT_DATA_DIR / "wechat_scraper_state.json"
)
DEFAULT_WECHAT_TEMP_CHUNKS_DIR = (
    DEFAULT_CHECKPOINT_DATA_DIR / "wechat_temp_chunks"
)
DEFAULT_IMPORT_CHECKPOINT_FILE = (
    DEFAULT_CHECKPOINT_DATA_DIR / "import_knowledge_base.json"
)
DEFAULT_PIPELINE_REPORTS_DIR = DEFAULT_REPORTS_DATA_DIR / "pipelines"
DEFAULT_WECHAT_RAW_CURRENT = (
    DEFAULT_CURRENT_DATA_DIR / "wechat_articles_all.json"
)
DEFAULT_KNOWLEDGE_BASE_CURRENT = (
    DEFAULT_CURRENT_DATA_DIR / "wechat_articles_processed.json"
)
LEGACY_WECHAT_RAW_INPUT = DEFAULT_DATA_DIR / "wechat_articles_all.json"
LEGACY_KNOWLEDGE_BASE_INPUT = (
    DEFAULT_DATA_DIR / "wechat_articles_processed.json"
)
DEFAULT_WECHAT_RAW_INPUT = DEFAULT_WECHAT_RAW_CURRENT
DEFAULT_KNOWLEDGE_BASE_INPUT = (
    DEFAULT_KNOWLEDGE_BASE_CURRENT
)


def import_checkpoint_file_for(input_file: Path) -> Path:
    if input_file == DEFAULT_KNOWLEDGE_BASE_INPUT:
        return DEFAULT_IMPORT_CHECKPOINT_FILE
    if input_file.parent.name == "current":
        return (
            input_file.parent.parent
            / "checkpoints"
            / "import_knowledge_base.json"
        )
    return input_file.parent / "checkpoints" / "import_knowledge_base.json"
