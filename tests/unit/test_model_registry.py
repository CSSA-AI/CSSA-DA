from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

from app.services.rag import model_registry


def test_embedding_model_is_loaded_once(monkeypatch):
    registry = model_registry.ModelRegistry()
    model = object()
    load_count = 0

    def load_model():
        nonlocal load_count
        load_count += 1
        return model

    monkeypatch.setattr(registry, "_load_embedding_model", load_model)

    with ThreadPoolExecutor(max_workers=4) as executor:
        models = list(
            executor.map(
                lambda _: registry.get_embedding_model(),
                range(8),
            )
        )

    assert models == [model] * 8
    assert load_count == 1


def test_reranker_model_is_loaded_once(monkeypatch):
    registry = model_registry.ModelRegistry()
    model = object()
    load_count = 0

    def load_model():
        nonlocal load_count
        load_count += 1
        return model

    monkeypatch.setattr(registry, "_load_reranker_model", load_model)

    assert registry.get_reranker_model() is model
    assert registry.get_reranker_model() is model
    assert load_count == 1


def test_preload_models_loads_both_models(monkeypatch):
    registry = model_registry.ModelRegistry()
    get_embedding_model = MagicMock(return_value=object())
    get_reranker_model = MagicMock(return_value=object())
    monkeypatch.setattr(
        registry,
        "get_embedding_model",
        get_embedding_model,
    )
    monkeypatch.setattr(
        registry,
        "get_reranker_model",
        get_reranker_model,
    )

    registry.preload_models()

    get_embedding_model.assert_called_once_with()
    get_reranker_model.assert_called_once_with()


def test_preload_models_records_failure_and_tries_both_models(monkeypatch):
    registry = model_registry.ModelRegistry()
    monkeypatch.setattr(
        registry,
        "_load_embedding_model",
        MagicMock(side_effect=RuntimeError("embedding failed")),
    )
    reranker_model = object()
    monkeypatch.setattr(
        registry,
        "_load_reranker_model",
        MagicMock(return_value=reranker_model),
    )

    try:
        registry.preload_models()
    except model_registry.ModelPreloadError:
        pass
    else:
        raise AssertionError("ModelPreloadError was not raised")

    status = registry.status()
    assert status.state == "failed"
    assert status.embedding == "failed"
    assert status.reranker == "ready"
    assert registry.get_reranker_model() is reranker_model


def test_load_embedding_model_uses_local_directory(tmp_path, monkeypatch):
    embedding_dir = tmp_path / "embedding"
    embedding_dir.mkdir()
    registry = model_registry.ModelRegistry()
    calls = []

    def build_model(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(
        model_registry.settings,
        "MODEL_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        model_registry,
        "SentenceTransformer",
        build_model,
    )

    registry.get_embedding_model()

    assert calls == [
        ((str(embedding_dir.resolve()),), {"local_files_only": True})
    ]


def test_load_reranker_model_uses_pinned_remote_model(monkeypatch):
    registry = model_registry.ModelRegistry()
    model = object()
    calls = []
    monkeypatch.setattr(model_registry.settings, "MODEL_DIR", None)
    monkeypatch.setattr(
        model_registry,
        "rag_config",
        {
            "reranker": {
                "model_name": "example/reranker",
                "model_revision": "revision-123",
                "adapter_path": None,
            }
        },
    )

    def build_model(*args, **kwargs):
        calls.append((args, kwargs))
        return model

    monkeypatch.setattr(model_registry, "CrossEncoder", build_model)

    assert registry.get_reranker_model() is model
    assert calls == [
        (("example/reranker",), {"revision": "revision-123"})
    ]


def test_load_reranker_model_applies_configured_adapter(monkeypatch):
    registry = model_registry.ModelRegistry()
    model = MagicMock()
    inner_model = model.model
    adapter_model = object()
    monkeypatch.setattr(model_registry.settings, "MODEL_DIR", None)
    monkeypatch.setattr(
        model_registry,
        "rag_config",
        {
            "reranker": {
                "model_name": "example/reranker",
                "model_revision": "revision-123",
                "adapter_path": "example/adapter",
            }
        },
    )
    monkeypatch.setattr(
        model_registry,
        "CrossEncoder",
        lambda *args, **kwargs: model,
    )
    mock_from_pretrained = MagicMock(return_value=adapter_model)
    monkeypatch.setattr(
        model_registry.PeftModel,
        "from_pretrained",
        mock_from_pretrained,
    )

    assert registry.get_reranker_model() is model
    mock_from_pretrained.assert_called_once_with(
        inner_model,
        "example/adapter",
    )
    assert model.model is adapter_model
