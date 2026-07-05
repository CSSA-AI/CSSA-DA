import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from app.core.config import rag_config
from pipelines.embedding.knowledge_base_text import encode_records
from pipelines.loaders.base import KnowledgeBaseLoader
from pipelines.loaders.postgres_knowledge_base import (
    PostgresKnowledgeBaseLoader,
)
from pipelines.shared.import_checkpoint import (
    ImportCheckpoint,
    ImportCheckpointIdentity,
    ImportCheckpointManager,
    ImportCheckpointStore,
    JsonImportCheckpointStore,
    build_import_checkpoint_identity,
    validate_import_checkpoint_identity,
)
from pipelines.shared.json_records import load_json_records
from pipelines.shared.paths import DEFAULT_KNOWLEDGE_BASE_INPUT
from pipelines.validation.knowledge_base_records import validate_records


logger = logging.getLogger(__name__)


class EmbeddingModel(Protocol):
    def encode(
        self,
        texts: list[str],
        *,
        normalize_embeddings: bool,
    ) -> Any: ...


class KnowledgeBaseValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(
            f"Refusing to import {len(errors)} validation errors"
        )


@dataclass(frozen=True)
class ImportResult:
    attempted_count: int
    inserted_count: int


def import_knowledge_base(
    records: list[dict[str, Any]],
    embedder: EmbeddingModel,
    loader: KnowledgeBaseLoader,
    *,
    batch_size: int = 100,
    checkpoint_store: ImportCheckpointStore | None = None,
    checkpoint_identity: ImportCheckpointIdentity | None = None,
) -> ImportResult:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    _validate_import_records(records)
    checkpoint_manager = None
    checkpoint = None
    if checkpoint_store is not None:
        if checkpoint_identity is None:
            raise ValueError(
                "checkpoint_identity is required with checkpoint_store"
            )
        validate_import_checkpoint_identity(
            records,
            checkpoint_identity,
            batch_size=batch_size,
        )
        checkpoint_manager = ImportCheckpointManager(
            checkpoint_store,
            checkpoint_identity,
            batch_count=math.ceil(len(records) / batch_size),
        )
        checkpoint = checkpoint_manager.prepare()
    if checkpoint is not None and checkpoint.status == "completed":
        return ImportResult(
            attempted_count=len(records),
            inserted_count=checkpoint.inserted_count,
        )

    return _import_validated_records(
        records,
        embedder,
        loader,
        batch_size=batch_size,
        checkpoint_manager=checkpoint_manager,
        checkpoint=checkpoint,
    )


def _validate_import_records(
    records: list[dict[str, Any]],
) -> None:
    started = time.perf_counter()
    logger.info(
        "Knowledge-base validation started",
        extra={
            "event": "stage_started",
            "stage": "validation",
            "record_count": len(records),
        },
    )
    errors = validate_records(records)
    if errors:
        logger.error(
            "Knowledge-base validation failed",
            extra={
                "event": "stage_failed",
                "stage": "validation",
                "record_count": len(records),
                "error_count": len(errors),
                "duration_seconds": round(
                    time.perf_counter() - started,
                    6,
                ),
                "error_type": "KnowledgeBaseValidationError",
            },
        )
        raise KnowledgeBaseValidationError(errors)
    logger.info(
        "Knowledge-base validation completed",
        extra={
            "event": "stage_completed",
            "stage": "validation",
            "record_count": len(records),
            "duration_seconds": round(
                time.perf_counter() - started,
                6,
            ),
        },
    )


def _import_validated_records(
    records: list[dict[str, Any]],
    embedder: EmbeddingModel,
    loader: KnowledgeBaseLoader,
    *,
    batch_size: int,
    checkpoint_manager: ImportCheckpointManager | None = None,
    checkpoint: ImportCheckpoint | None = None,
) -> ImportResult:
    if not records:
        if checkpoint_manager is not None and checkpoint is not None:
            checkpoint_manager.mark_completed(
                checkpoint,
                inserted_count=checkpoint.inserted_count,
            )
        return ImportResult(attempted_count=0, inserted_count=0)

    inserted_count = checkpoint.inserted_count if checkpoint else 0
    batch_count = math.ceil(len(records) / batch_size)
    start_batch_index = (
        checkpoint.next_batch_index if checkpoint else 0
    )
    for batch_index in range(start_batch_index, batch_count):
        start = batch_index * batch_size
        batch = records[start : start + batch_size]
        logger.info(
            "Import batch started",
            extra={
                "event": "batch_started",
                "stage": "import",
                "batch_number": batch_index + 1,
                "batch_count": batch_count,
                "record_count": len(batch),
            },
        )
        try:
            embeddings = encode_records(batch, embedder)
            batch_inserted_count = loader.insert_batch(batch, embeddings)
        except Exception as error:
            logger.exception(
                "Import batch failed",
                extra={
                    "event": "batch_failed",
                    "stage": "import",
                    "batch_number": batch_index + 1,
                    "batch_count": batch_count,
                    "record_count": len(batch),
                    "error_type": type(error).__name__,
                },
            )
            if checkpoint_manager is not None and checkpoint is not None:
                checkpoint = checkpoint_manager.mark_failed(
                    checkpoint,
                    next_batch_index=batch_index,
                    inserted_count=inserted_count,
                    error=error,
                )
            raise
        inserted_count += batch_inserted_count
        if checkpoint_manager is not None and checkpoint is not None:
            checkpoint = checkpoint_manager.mark_batch_completed(
                checkpoint,
                next_batch_index=batch_index + 1,
                inserted_count=inserted_count,
            )
        logger.info(
            "Import batch completed",
            extra={
                "event": "batch_completed",
                "stage": "import",
                "batch_number": batch_index + 1,
                "batch_count": batch_count,
                "record_count": len(batch),
                "inserted_count": batch_inserted_count,
            },
        )

    if checkpoint_manager is not None and checkpoint is not None:
        checkpoint_manager.mark_completed(
            checkpoint,
            inserted_count=inserted_count,
        )

    return ImportResult(
        attempted_count=len(records),
        inserted_count=inserted_count,
    )


def run_local_import(
    database_url: str,
    *,
    input_file: Path = DEFAULT_KNOWLEDGE_BASE_INPUT,
    model_name: str | None = None,
    table_name: str | None = None,
    limit: int | None = None,
    batch_size: int = 100,
    checkpoint_file: Path | None = None,
    reset_checkpoint: bool = False,
) -> ImportResult:
    if limit is not None and limit < 0:
        raise ValueError("limit cannot be negative")
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    records = load_json_records(input_file)
    if limit is not None:
        records = records[:limit]

    _validate_import_records(records)
    model_name = model_name or rag_config["retriever"]["embedding_model"]
    table_name = table_name or rag_config["pgvector"]["table_name"]
    checkpoint_store = JsonImportCheckpointStore(
        checkpoint_file
        or input_file.parent / "import_checkpoint.json"
    )
    if reset_checkpoint:
        checkpoint_store.clear()

    checkpoint_identity = build_import_checkpoint_identity(
        records,
        model_name=model_name,
        table_name=table_name,
        target_id=database_target_id(database_url),
        batch_size=batch_size,
    )
    checkpoint_manager = ImportCheckpointManager(
        checkpoint_store,
        checkpoint_identity,
        batch_count=math.ceil(len(records) / batch_size),
    )
    checkpoint = checkpoint_manager.prepare()
    if checkpoint is not None and checkpoint.status == "completed":
        return ImportResult(
            attempted_count=len(records),
            inserted_count=checkpoint.inserted_count,
        )
    if not records:
        checkpoint_manager.mark_completed(
            checkpoint,
            inserted_count=checkpoint.inserted_count,
        )
        return ImportResult(attempted_count=0, inserted_count=0)

    from sentence_transformers import SentenceTransformer

    embedder = SentenceTransformer(model_name)
    with PostgresKnowledgeBaseLoader(
        database_url,
        table_name,
        expected_embedding_dim=rag_config["retriever"]["embedding_dim"],
    ) as loader:
        return _import_validated_records(
            records,
            embedder,
            loader,
            batch_size=batch_size,
            checkpoint_manager=checkpoint_manager,
            checkpoint=checkpoint,
        )


def database_target_id(database_url: str) -> str:
    parsed = urlparse(database_url)
    database_name = parsed.path.lstrip("/")
    if not parsed.hostname or not database_name:
        raise ValueError("database_url must include a host and database name")

    port = f":{parsed.port}" if parsed.port else ""
    return (
        f"{parsed.scheme}://{parsed.hostname}{port}/{database_name}"
    )
