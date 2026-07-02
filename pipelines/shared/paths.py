from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KNOWLEDGE_BASE_INPUT = PROJECT_ROOT / "data" / "wechat_articles_processed.json"
