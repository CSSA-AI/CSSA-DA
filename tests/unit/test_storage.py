from pathlib import Path

import pytest

from pipelines.shared.storage import (
    LocalStorage,
    Storage,
    StorageNotFoundError,
)


def test_local_storage_satisfies_storage_protocol(tmp_path: Path):
    assert isinstance(LocalStorage(tmp_path), Storage)


def test_write_then_read_round_trips_bytes(tmp_path: Path):
    storage = LocalStorage(tmp_path)

    storage.write("reports/run.json", b"payload")

    assert storage.read("reports/run.json") == b"payload"


def test_write_creates_nested_directories(tmp_path: Path):
    storage = LocalStorage(tmp_path)

    storage.write("checkpoints/wechat/state.json", b"{}")

    assert (tmp_path / "checkpoints" / "wechat" / "state.json").is_file()


def test_write_maps_key_onto_base_dir_layout(tmp_path: Path):
    storage = LocalStorage(tmp_path)

    storage.write("reports/pipelines/import.json", b"{}")

    assert (tmp_path / "reports" / "pipelines" / "import.json").read_bytes() == b"{}"


def test_write_overwrites_existing_value(tmp_path: Path):
    storage = LocalStorage(tmp_path)

    storage.write("current/articles.json", b"old")
    storage.write("current/articles.json", b"new")

    assert storage.read("current/articles.json") == b"new"


def test_write_leaves_no_temporary_file_behind(tmp_path: Path):
    storage = LocalStorage(tmp_path)

    storage.write("current/articles.json", b"payload")

    assert list(tmp_path.rglob("*.tmp")) == []


def test_read_missing_key_raises_storage_not_found(tmp_path: Path):
    storage = LocalStorage(tmp_path)

    with pytest.raises(StorageNotFoundError):
        storage.read("does/not/exist.json")


def test_exists_reflects_presence(tmp_path: Path):
    storage = LocalStorage(tmp_path)

    assert storage.exists("checkpoints/state.json") is False
    storage.write("checkpoints/state.json", b"{}")
    assert storage.exists("checkpoints/state.json") is True


def test_list_returns_sorted_keys_under_prefix(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    storage.write("raw/wechat/batch_2.json", b"[]")
    storage.write("raw/wechat/batch_1.json", b"[]")
    storage.write("processed/other.json", b"[]")

    assert storage.list("raw/wechat/") == [
        "raw/wechat/batch_1.json",
        "raw/wechat/batch_2.json",
    ]


def test_list_ignores_temporary_files(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    storage.write("raw/batch_1.json", b"[]")
    (tmp_path / "raw" / "batch_1.json.tmp").write_bytes(b"partial")

    assert storage.list("raw/") == ["raw/batch_1.json"]


def test_list_missing_prefix_returns_empty(tmp_path: Path):
    storage = LocalStorage(tmp_path)

    assert storage.list("nothing/here/") == []


def test_delete_removes_key(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    storage.write("checkpoints/state.json", b"{}")

    storage.delete("checkpoints/state.json")

    assert storage.exists("checkpoints/state.json") is False


def test_delete_missing_key_is_not_an_error(tmp_path: Path):
    storage = LocalStorage(tmp_path)

    storage.delete("checkpoints/state.json")


def test_delete_prefix_removes_whole_subtree(tmp_path: Path):
    storage = LocalStorage(tmp_path)
    storage.write("checkpoints/temp/batch_0.json", b"[]")
    storage.write("checkpoints/temp/batch_1.json", b"[]")
    storage.write("checkpoints/state.json", b"{}")

    storage.delete_prefix("checkpoints/temp")

    assert storage.list("checkpoints/") == ["checkpoints/state.json"]
