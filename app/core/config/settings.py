from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


CONFIG_DIR = Path(__file__).resolve().parent
RAG_CONFIG_PATH = CONFIG_DIR / "rag-config.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENV: str = "dev"

    OPENAI_API_KEY: str | None = None
    CHAT_API_KEY: str | None = None
    WECHAT_API_KEY: str | None = None
    DATABASE_URL: str | None = None


def load_yaml_config(path: Path = RAG_CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


settings = Settings()
rag_config = load_yaml_config()
