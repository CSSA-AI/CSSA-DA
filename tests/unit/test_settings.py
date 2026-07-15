from pathlib import Path

import pytest

from app.core.config.settings import Settings


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
