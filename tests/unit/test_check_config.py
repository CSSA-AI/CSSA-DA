import pytest

from ops import check_config


def clear_env(monkeypatch):
    for name in (
        "ENV",
        "DATABASE_URL",
        "OPENAI_API_KEY",
        "CHAT_API_KEY",
        "WECHAT_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(check_config.settings, name, None)


def test_api_profile_requires_database_and_openai(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")

    status = check_config.check_config("api")

    assert status.ok is False
    variables = {item.name: item for item in status.variables}
    assert variables["DATABASE_URL"].required is True
    assert variables["DATABASE_URL"].configured is True
    assert variables["OPENAI_API_KEY"].required is True
    assert variables["OPENAI_API_KEY"].configured is False
    assert variables["CHAT_API_KEY"].required is True
    assert variables["CHAT_API_KEY"].configured is False
    assert variables["WECHAT_API_KEY"].required is False


def test_pipeline_profile_only_requires_database(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")

    status = check_config.check_config("pipeline")

    assert status.ok is True
    variables = {item.name: item for item in status.variables}
    assert variables["DATABASE_URL"].required is True
    assert variables["OPENAI_API_KEY"].required is False
    assert variables["CHAT_API_KEY"].required is False
    assert variables["WECHAT_API_KEY"].required is False


def test_harvester_profile_requires_wechat_key(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("WECHAT_API_KEY", "secret-wechat-key")

    status = check_config.check_config("harvester")

    assert status.ok is True
    variables = {item.name: item for item in status.variables}
    assert variables["WECHAT_API_KEY"].required is True
    assert variables["WECHAT_API_KEY"].configured is True
    assert "secret-wechat-key" not in str(status.to_dict())


def test_all_profile_requires_every_external_service(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-openai-key")
    monkeypatch.setenv("CHAT_API_KEY", "secret-chat-key")
    monkeypatch.setenv("WECHAT_API_KEY", "secret-wechat-key")

    status = check_config.check_config("all")

    assert status.ok is True
    assert "secret-openai-key" not in str(status.to_dict())
    assert "secret-chat-key" not in str(status.to_dict())
    assert "secret-wechat-key" not in str(status.to_dict())


def test_invalid_profile_is_rejected():
    with pytest.raises(ValueError, match="profile must be one of"):
        check_config.check_config("unknown")
