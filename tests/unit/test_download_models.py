import pytest

from ops import download_models


TEST_CONFIG = {
    "retriever": {
        "embedding_model": "example/embedding-model",
        "embedding_revision": "embedding-revision",
    },
    "reranker": {
        "model_name": "example/reranker-model",
        "model_revision": "reranker-revision",
    },
}


def test_download_filter_excludes_duplicate_model_formats():
    assert download_models.IGNORED_MODEL_FILES == [
        "*.bin",
        "*.h5",
        "*.msgpack",
        "onnx/*",
        "openvino/*",
    ]


def test_get_model_downloads_reads_models_from_config():
    models = download_models.get_model_downloads(TEST_CONFIG)

    assert models == [
        download_models.ModelDownload(
            name="embedding",
            repo_id="example/embedding-model",
            revision="embedding-revision",
        ),
        download_models.ModelDownload(
            name="reranker",
            repo_id="example/reranker-model",
            revision="reranker-revision",
        ),
    ]


def test_get_model_downloads_requires_pinned_revision():
    config = {
        **TEST_CONFIG,
        "reranker": {"model_name": "example/reranker-model"},
    }

    with pytest.raises(
        ValueError,
        match="Pinned model revision is required for reranker",
    ):
        download_models.get_model_downloads(config)


def test_download_models_uses_separate_local_directories(tmp_path, monkeypatch):
    calls = []

    def record_download(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(download_models, "snapshot_download", record_download)

    paths = download_models.download_models(tmp_path, TEST_CONFIG)

    assert paths == [
        tmp_path / "embedding",
        tmp_path / "reranker",
    ]
    assert calls == [
        {
            "repo_id": "example/embedding-model",
            "revision": "embedding-revision",
            "local_dir": tmp_path / "embedding",
            "ignore_patterns": download_models.IGNORED_MODEL_FILES,
        },
        {
            "repo_id": "example/reranker-model",
            "revision": "reranker-revision",
            "local_dir": tmp_path / "reranker",
            "ignore_patterns": download_models.IGNORED_MODEL_FILES,
        },
    ]


def test_main_requires_target_directory(monkeypatch):
    monkeypatch.setattr("sys.argv", ["download_models.py"])

    with pytest.raises(SystemExit) as exc_info:
        download_models.main()

    assert exc_info.value.code == 2
