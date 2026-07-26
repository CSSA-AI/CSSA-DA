from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Local storage root. Logical keys below are resolved relative to this
# directory by ``LocalStorage``; in the cloud the same keys live under an S3
# bucket. Artifacts are always addressed by logical key, never by filesystem
# path (see docs/design/storage-abstraction.md).
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

# Logical storage keys (``/``-separated, relative to the storage root).
WECHAT_CHECKPOINT_KEY = "checkpoints/wechat_scraper_state.json"
WECHAT_TEMP_CHUNKS_PREFIX = "checkpoints/wechat_temp_chunks"
WECHAT_RAW_DIR_KEY = "raw/wechat"
WECHAT_RAW_CURRENT_KEY = "current/wechat_articles_all.json"
KNOWLEDGE_BASE_PROCESSED_DIR_KEY = "processed/knowledge_base"
KNOWLEDGE_BASE_CURRENT_KEY = "current/wechat_articles_processed.json"
IMPORT_CHECKPOINT_KEY = "checkpoints/import_knowledge_base.json"
PIPELINE_REPORTS_PREFIX = "reports/pipelines"

# Default logical keys for CLI inputs.
DEFAULT_WECHAT_RAW_INPUT_KEY = WECHAT_RAW_CURRENT_KEY
DEFAULT_KNOWLEDGE_BASE_INPUT_KEY = KNOWLEDGE_BASE_CURRENT_KEY
