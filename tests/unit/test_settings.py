from pathlib import Path

import pytest

from app.core.config.settings import Settings


def test_rate_limit_defaults():
    settings = Settings(_env_file=None)

    assert settings.CHAT_RATE_LIMIT == "10/minute"
    # Sized to fit under the $20/month OpenAI project hard cap
    # (docs/openai-spend-cap.md); change both together.
    assert settings.CHAT_GLOBAL_RATE_LIMIT == "500/day"


def test_local_model_path_is_disabled_by_default():
    settings = Settings(_env_file=None)

    assert settings.local_model_path("embedding") is None


def test_local_model_path_resolves_existing_subdirectory(tmp_path):
    (tmp_path / "embedding").mkdir()
    settings = Settings(MODEL_DIR=tmp_path, _env_file=None)

    assert settings.local_model_path("embedding") == (
        tmp_path / "embedding"
    ).resolve()


def test_local_model_path_rejects_missing_subdirectory(tmp_path):
    settings = Settings(MODEL_DIR=tmp_path, _env_file=None)

    with pytest.raises(FileNotFoundError, match="Local model directory not found"):
        settings.local_model_path("reranker")


def test_database_url_is_left_alone_when_given_directly():
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql://someone:somewhere@localhost:5432/local",
        DB_HOST="ignored.rds.amazonaws.com",
        DB_NAME="ignored",
        DB_USER="ignored",
        DB_PASSWORD="ignored",
    )

    # An explicit value wins, so local and test configuration is unaffected by
    # the parts being present.
    assert settings.DATABASE_URL == (
        "postgresql://someone:somewhere@localhost:5432/local"
    )


def test_database_url_is_assembled_from_its_parts():
    settings = Settings(
        _env_file=None,
        DB_HOST="cssa-da-prod-db.ap-southeast-2.rds.amazonaws.com",
        DB_NAME="rag_vectordb",
        DB_USER="cssa_admin",
        DB_PASSWORD="plain",
    )

    assert settings.DATABASE_URL == (
        "postgresql://cssa_admin:plain"
        "@cssa-da-prod-db.ap-southeast-2.rds.amazonaws.com:5432/rag_vectordb"
    )


def test_assembled_password_is_percent_encoded():
    # RDS generates the password, and the generated one is not chosen to be
    # URL-safe. Without encoding, the '@' below ends the credentials early and
    # the host parses as "pass/word@host" -- which surfaces as an unresolvable
    # host rather than as a credential problem.
    settings = Settings(
        _env_file=None,
        DB_HOST="db.internal",
        DB_NAME="rag_vectordb",
        DB_USER="cssa_admin",
        DB_PASSWORD="p@ss/word:1+2=3",
    )

    assert settings.DATABASE_URL == (
        "postgresql://cssa_admin:p%40ss%2Fword%3A1%2B2%3D3"
        "@db.internal:5432/rag_vectordb"
    )


def test_database_url_stays_none_when_parts_are_incomplete():
    settings = Settings(
        _env_file=None,
        DB_HOST="db.internal",
        DB_NAME="rag_vectordb",
        # No user or password: half a configuration is not a connection string.
    )

    assert settings.DATABASE_URL is None
