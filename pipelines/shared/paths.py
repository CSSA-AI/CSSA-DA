from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_WECHAT_RAW_INPUT = DEFAULT_DATA_DIR / "wechat_articles_all.json"
DEFAULT_KNOWLEDGE_BASE_INPUT = (
    DEFAULT_DATA_DIR / "wechat_articles_processed.json"
)
