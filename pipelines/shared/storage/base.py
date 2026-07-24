"""Storage abstraction for pipeline artifacts.

Pipeline stages read and write artifacts -- raw/processed data, checkpoints and
reports -- through this small, transport-neutral interface. The same stage code
can then run against the local filesystem during development and against an
object store (for example Amazon S3) in the cloud, by swapping the ``Storage``
implementation without touching stage code.

Keys are ``/``-separated strings, for example ``"reports/pipelines/import.json"``.
A key is a *location name*, not a filesystem path: each backend maps keys onto
its own storage layout.
"""

from typing import Protocol, runtime_checkable


class StorageNotFoundError(KeyError):
    """Raised by ``Storage.read`` when the requested key does not exist."""


@runtime_checkable
class Storage(Protocol):
    def write(self, key: str, data: bytes) -> None:
        """Store ``data`` under ``key``, replacing any existing value.

        The write is atomic: a reader either sees the previous value or the new
        one, never a partially written artifact.
        """
        ...

    def read(self, key: str) -> bytes:
        """Return the bytes stored under ``key``.

        Raises ``StorageNotFoundError`` if the key does not exist.
        """
        ...

    def exists(self, key: str) -> bool:
        """Return whether ``key`` currently holds a value."""
        ...

    def list(self, prefix: str) -> list[str]:
        """Return all keys that start with ``prefix``, sorted."""
        ...

    def delete(self, key: str) -> None:
        """Delete ``key``. A missing key is not an error."""
        ...

    def delete_prefix(self, prefix: str) -> None:
        """Delete every key that starts with ``prefix``."""
        ...
