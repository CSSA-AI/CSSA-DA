"""Filesystem-backed :class:`Storage` implementation for local development."""

import shutil
from pathlib import Path

from pipelines.shared.storage.base import StorageNotFoundError


class LocalStorage:
    """Store artifacts on the local filesystem under ``base_dir``.

    A key is resolved relative to ``base_dir``, so the on-disk layout is
    identical to the pre-abstraction pipeline: with ``base_dir`` pointing at
    ``data/``, the key ``"reports/pipelines/import.json"`` maps to
    ``data/reports/pipelines/import.json``.

    Writes go through a temporary file and an atomic rename, so a crash
    mid-write never leaves a partially written artifact behind. Temporary
    ``.tmp`` files are ignored by ``list`` and ``delete_prefix``.
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def _path(self, key: str) -> Path:
        return self.base_dir / key

    def write(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = path.with_suffix(f"{path.suffix}.tmp")
        temporary_file.write_bytes(data)
        temporary_file.replace(path)

    def read(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as error:
            raise StorageNotFoundError(key) from error

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def list(self, prefix: str) -> list[str]:
        target = self._path(prefix)
        search_root = target if target.is_dir() else target.parent
        if not search_root.exists():
            return []

        keys = []
        for path in search_root.rglob("*"):
            if not path.is_file() or path.suffix == ".tmp":
                continue
            key = path.relative_to(self.base_dir).as_posix()
            if key.startswith(prefix):
                keys.append(key)
        return sorted(keys)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        target = self._path(prefix)
        if target.is_dir():
            shutil.rmtree(target)
            return
        for key in self.list(prefix):
            self._path(key).unlink(missing_ok=True)
