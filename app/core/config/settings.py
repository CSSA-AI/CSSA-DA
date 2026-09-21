from pathlib import Path
from typing import Any

import yaml
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.database_url import build_database_url


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

    # Assembled into DATABASE_URL when that is not set, which is how the
    # deployed container is configured: RDS keeps the credentials in Secrets
    # Manager as separate fields, and ECS can inject a field of a secret but
    # cannot concatenate one. Locally DATABASE_URL is set directly and these
    # stay empty.
    DB_HOST: str | None = None
    DB_PORT: int = 5432
    DB_NAME: str | None = None
    DB_USER: str | None = None
    DB_PASSWORD: str | None = None

    MODEL_DIR: Path | None = None
    LOG_LEVEL: str = "INFO"
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:5173"
    CHAT_RATE_LIMIT: str = "10/minute"
    # Site-wide /chat budget shared by ALL clients (one counter, not per-IP):
    # rotating IPs cannot bypass it (ROADMAP 19.4). Sized to stay under the
    # $20/month OpenAI project hard cap (docs/openai-spend-cap.md). "day"
    # means 24h from the window's first request, not a calendar day, and the
    # counter resets on process restart.
    CHAT_GLOBAL_RATE_LIMIT: str = "500/day"

    # Rejects a request before its body is read/parsed (and therefore before
    # auth, which FastAPI resolves after body parsing) once it exceeds this
    # many bytes. ChatRequest's field caps (message 10k + chat_history 20 x
    # 4k chars, UTF-8 worst case ~3 bytes/char) bound a legitimate request to
    # ~270KB; 512KB leaves headroom without letting an unauthenticated caller
    # make the server buffer/parse an arbitrarily large body.
    MAX_REQUEST_BODY_BYTES: int = 512 * 1024

    # Deploy-time coordinates stamped onto every chat_interactions row's
    # config fingerprint (ROADMAP_rag.md Phase 4.5). Optional: unset means the
    # fingerprint records null, which is honest. GIT_SHA is the "which code"
    # coordinate and equals the image tag (CONTRIBUTING.md "Four version
    # coordinates"); CORPUS_SHA256 is what lets an online row and an offline
    # eval report be compared on the same ruler.
    GIT_SHA: str | None = None
    CORPUS_SHA256: str | None = None

    @model_validator(mode="after")
    def _assemble_database_url(self) -> "Settings":
        """Fill DATABASE_URL in from its parts when it was not given directly.

        An explicit DATABASE_URL always wins, so nothing about local or test
        configuration changes. Everything downstream keeps reading
        `settings.DATABASE_URL` and never learns where it came from.

        The rule itself lives in `app.core.database_url`, because Alembic needs
        the same one and does not go through `Settings` -- see the note there.
        """
        if self.DATABASE_URL:
            return self

        self.DATABASE_URL = build_database_url(
            host=self.DB_HOST,
            port=self.DB_PORT,
            name=self.DB_NAME,
            user=self.DB_USER,
            password=self.DB_PASSWORD,
        )
        return self

    @property
    def allowed_origins_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]

    def local_model_path(self, model_name: str) -> Path | None:
        if self.MODEL_DIR is None:
            return None

        model_path = (self.MODEL_DIR / model_name).resolve()
        if not model_path.is_dir():
            raise FileNotFoundError(f"Local model directory not found: {model_path}")

        return model_path


def load_yaml_config(path: Path = RAG_CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


settings = Settings()
rag_config = load_yaml_config()
