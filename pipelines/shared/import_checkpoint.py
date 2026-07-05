import hashlib
import json
import logging
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Protocol


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportCheckpointIdentity:
    dataset_fingerprint: str
    model_name: str
    table_name: str
    target_id: str
    batch_size: int
    record_count: int


@dataclass(frozen=True)
class ImportCheckpoint:
    identity: ImportCheckpointIdentity
    next_batch_index: int = 0
    inserted_count: int = 0
    status: str = "running"
    error: str | None = None


class ImportCheckpointStore(Protocol):
    def load(self) -> ImportCheckpoint | None: ...

    def save(self, checkpoint: ImportCheckpoint) -> None: ...

    def clear(self) -> None: ...


class JsonImportCheckpointStore:
    def __init__(self, checkpoint_file: Path):
        self.checkpoint_file = checkpoint_file

    def load(self) -> ImportCheckpoint | None:
        if not self.checkpoint_file.exists():
            return None

        with self.checkpoint_file.open("r", encoding="utf-8") as file:
            payload = json.load(file)

        return ImportCheckpoint(
            identity=ImportCheckpointIdentity(**payload["identity"]),
            next_batch_index=payload["next_batch_index"],
            inserted_count=payload["inserted_count"],
            status=payload["status"],
            error=payload.get("error"),
        )

    def save(self, checkpoint: ImportCheckpoint) -> None:
        self.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = self.checkpoint_file.with_suffix(
            f"{self.checkpoint_file.suffix}.tmp"
        )

        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(
                asdict(checkpoint),
                file,
                ensure_ascii=False,
                indent=2,
            )

        temporary_file.replace(self.checkpoint_file)

    def clear(self) -> None:
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()


class MemoryImportCheckpointStore:
    def __init__(self):
        self._checkpoint: ImportCheckpoint | None = None

    def load(self) -> ImportCheckpoint | None:
        return deepcopy(self._checkpoint)

    def save(self, checkpoint: ImportCheckpoint) -> None:
        self._checkpoint = deepcopy(checkpoint)

    def clear(self) -> None:
        self._checkpoint = None


class ImportCheckpointManager:
    def __init__(
        self,
        store: ImportCheckpointStore,
        identity: ImportCheckpointIdentity,
        *,
        batch_count: int,
    ):
        self.store = store
        self.identity = identity
        self.batch_count = batch_count

    def prepare(self) -> ImportCheckpoint:
        checkpoint = self.store.load()
        if checkpoint is None or checkpoint.identity != self.identity:
            checkpoint = ImportCheckpoint(identity=self.identity)
            self.store.save(checkpoint)
            self._log_checkpoint("checkpoint_started", checkpoint)
            return checkpoint

        if not 0 <= checkpoint.next_batch_index <= self.batch_count:
            raise ValueError(
                "Import checkpoint has an invalid next_batch_index"
            )
        if checkpoint.status == "completed":
            self._log_checkpoint("checkpoint_completed", checkpoint)
            return checkpoint

        checkpoint = replace(
            checkpoint,
            status="running",
            error=None,
        )
        self.store.save(checkpoint)
        self._log_checkpoint("checkpoint_resumed", checkpoint)
        return checkpoint

    def mark_batch_completed(
        self,
        checkpoint: ImportCheckpoint,
        *,
        next_batch_index: int,
        inserted_count: int,
    ) -> ImportCheckpoint:
        checkpoint = replace(
            checkpoint,
            next_batch_index=next_batch_index,
            inserted_count=inserted_count,
            status="running",
            error=None,
        )
        self.store.save(checkpoint)
        return checkpoint

    def mark_failed(
        self,
        checkpoint: ImportCheckpoint,
        *,
        next_batch_index: int,
        inserted_count: int,
        error: Exception,
    ) -> ImportCheckpoint:
        checkpoint = replace(
            checkpoint,
            next_batch_index=next_batch_index,
            inserted_count=inserted_count,
            status="failed",
            error=str(error),
        )
        self.store.save(checkpoint)
        self._log_checkpoint("checkpoint_failed", checkpoint)
        return checkpoint

    def mark_completed(
        self,
        checkpoint: ImportCheckpoint,
        *,
        inserted_count: int,
    ) -> ImportCheckpoint:
        checkpoint = replace(
            checkpoint,
            next_batch_index=self.batch_count,
            inserted_count=inserted_count,
            status="completed",
            error=None,
        )
        self.store.save(checkpoint)
        self._log_checkpoint("checkpoint_completed", checkpoint)
        return checkpoint

    def _log_checkpoint(
        self,
        event: str,
        checkpoint: ImportCheckpoint,
    ) -> None:
        log = (
            logger.error
            if checkpoint.status == "failed"
            else logger.info
        )
        log(
            "Import checkpoint %s",
            checkpoint.status,
            extra={
                "event": event,
                "stage": "import",
                "batch_count": self.batch_count,
                "inserted_count": checkpoint.inserted_count,
                "checkpoint_status": checkpoint.status,
                "next_batch_index": checkpoint.next_batch_index,
                "dataset_fingerprint": (
                    checkpoint.identity.dataset_fingerprint
                ),
                "model_name": checkpoint.identity.model_name,
                "table_name": checkpoint.identity.table_name,
                "target_id": checkpoint.identity.target_id,
            },
        )


def build_import_checkpoint_identity(
    records: list[dict[str, Any]],
    *,
    model_name: str,
    table_name: str,
    target_id: str,
    batch_size: int,
) -> ImportCheckpointIdentity:
    return ImportCheckpointIdentity(
        dataset_fingerprint=fingerprint_records(records),
        model_name=model_name,
        table_name=table_name,
        target_id=target_id,
        batch_size=batch_size,
        record_count=len(records),
    )


def validate_import_checkpoint_identity(
    records: list[dict[str, Any]],
    identity: ImportCheckpointIdentity,
    *,
    batch_size: int,
) -> None:
    if identity.batch_size != batch_size:
        raise ValueError(
            "checkpoint identity batch_size does not match import batch_size"
        )
    if identity.record_count != len(records):
        raise ValueError(
            "checkpoint identity record_count does not match records"
        )
    if identity.dataset_fingerprint != fingerprint_records(records):
        raise ValueError(
            "checkpoint identity fingerprint does not match records"
        )


def fingerprint_records(records: list[dict[str, Any]]) -> str:
    canonical_records = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return hashlib.sha256(canonical_records.encode("utf-8")).hexdigest()


def _json_default(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
