import hashlib
import logging
import math
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import uuid4

import psycopg2
from psycopg2.errors import UndefinedTable

from app.core.config import rag_config
from app.services.knowledge_base import count_active_rows, count_corpus_rows
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
from pipelines.shared.paths import (
    DEFAULT_KNOWLEDGE_BASE_INPUT_KEY,
    IMPORT_CHECKPOINT_KEY,
    PIPELINE_REPORTS_PREFIX,
)
from pipelines.shared.reports import write_json_report
from pipelines.shared.storage import Storage
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


class KnowledgeBaseImportIncompleteError(RuntimeError):
    """The import finished, but the table does not hold what it imported."""


@dataclass(frozen=True)
class ImportResult:
    attempted_count: int
    affected_count: int
    # Filled in by run_local_import, which is the only caller that knows the
    # target database and writes the import report. import_knowledge_base()
    # leaves them unset. See pipelines/README.md "Import batching" for what
    # each one means.
    corpus_sha256: str | None = None
    knowledge_base_rows: int | None = None
    unique_record_count: int | None = None
    rows_outside_corpus: int | None = None
    skipped_by_checkpoint: bool | None = None
    report_key: str | None = None


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
            affected_count=checkpoint.affected_count,
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
                affected_count=checkpoint.affected_count,
            )
        return ImportResult(attempted_count=0, affected_count=0)

    affected_count = checkpoint.affected_count if checkpoint else 0
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
            batch_affected_count = loader.load_batch(batch, embeddings)
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
                    affected_count=affected_count,
                    error=error,
                )
            raise
        affected_count += batch_affected_count
        if checkpoint_manager is not None and checkpoint is not None:
            checkpoint = checkpoint_manager.mark_batch_completed(
                checkpoint,
                next_batch_index=batch_index + 1,
                affected_count=affected_count,
            )
        logger.info(
            "Import batch completed",
            extra={
                "event": "batch_completed",
                "stage": "import",
                "batch_number": batch_index + 1,
                "batch_count": batch_count,
                "record_count": len(batch),
                "affected_count": batch_affected_count,
            },
        )

    if checkpoint_manager is not None and checkpoint is not None:
        checkpoint_manager.mark_completed(
            checkpoint,
            affected_count=affected_count,
        )

    return ImportResult(
        attempted_count=len(records),
        affected_count=affected_count,
    )


def run_local_import(
    storage: Storage,
    database_url: str,
    *,
    input_key: str = DEFAULT_KNOWLEDGE_BASE_INPUT_KEY,
    model_name: str | None = None,
    model_revision: str | None = None,
    table_name: str | None = None,
    limit: int | None = None,
    batch_size: int = 100,
    checkpoint_key: str | None = None,
    reset_checkpoint: bool = False,
    run_id: str | None = None,
) -> ImportResult:
    if limit is not None and limit < 0:
        raise ValueError("limit cannot be negative")
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    run_id = run_id or str(uuid4())
    started_at = datetime.now(timezone.utc)
    records = load_json_records(storage, input_key)
    if limit is not None:
        records = records[:limit]

    _validate_import_records(records)
    configured_model_name = rag_config["retriever"]["embedding_model"]
    model_name = model_name or configured_model_name
    if (
        model_revision is None
        and model_name == configured_model_name
    ):
        model_revision = rag_config["retriever"].get(
            "embedding_revision"
        )
    table_name = table_name or rag_config["pgvector"]["table_name"]
    checkpoint_store = JsonImportCheckpointStore(
        storage,
        checkpoint_key or IMPORT_CHECKPOINT_KEY,
    )
    if reset_checkpoint:
        checkpoint_store.clear()

    checkpoint_identity = build_import_checkpoint_identity(
        records,
        model_name=model_name,
        table_name=table_name,
        target_id=database_target_id(database_url),
        batch_size=batch_size,
        model_revision=model_revision,
    )
    checkpoint_manager = ImportCheckpointManager(
        checkpoint_store,
        checkpoint_identity,
        batch_count=math.ceil(len(records) / batch_size),
    )
    result, skipped_by_checkpoint = _run_checkpointed_import(
        records,
        database_url,
        model_name=model_name,
        model_revision=model_revision,
        table_name=table_name,
        batch_size=batch_size,
        checkpoint_manager=checkpoint_manager,
    )
    return _verify_and_report(
        storage,
        result,
        records,
        database_url,
        run_id=run_id,
        started_at=started_at,
        input_key=input_key,
        limit=limit,
        skipped_by_checkpoint=skipped_by_checkpoint,
        # The checkpoint already hashed exactly these records, after --limit.
        # Reusing it means "which corpus" has one definition, and it is taken
        # from what was imported rather than recomputed from a file later.
        corpus_sha256=checkpoint_identity.dataset_fingerprint,
        model_name=model_name,
        model_revision=model_revision,
        table_name=table_name,
    )


def _run_checkpointed_import(
    records: list[dict[str, Any]],
    database_url: str,
    *,
    model_name: str,
    model_revision: str | None,
    table_name: str,
    batch_size: int,
    checkpoint_manager: ImportCheckpointManager,
) -> tuple[ImportResult, bool]:
    """Import, or skip because the checkpoint says it is done -- and say which."""
    checkpoint = checkpoint_manager.prepare()
    if checkpoint is not None and checkpoint.status == "completed":
        return (
            ImportResult(
                attempted_count=len(records),
                affected_count=checkpoint.affected_count,
            ),
            True,
        )
    if not records:
        checkpoint_manager.mark_completed(
            checkpoint,
            affected_count=checkpoint.affected_count,
        )
        return ImportResult(attempted_count=0, affected_count=0), False

    from sentence_transformers import SentenceTransformer

    model_kwargs = (
        {"revision": model_revision}
        if model_revision
        else {}
    )
    embedder = SentenceTransformer(model_name, **model_kwargs)
    with PostgresKnowledgeBaseLoader(
        database_url,
        table_name,
        embedding_model=model_name,
        embedding_revision=model_revision,
        expected_embedding_dim=rag_config["retriever"]["embedding_dim"],
    ) as loader:
        result = _import_validated_records(
            records,
            embedder,
            loader,
            batch_size=batch_size,
            checkpoint_manager=checkpoint_manager,
            checkpoint=checkpoint,
        )
    return result, False


@dataclass(frozen=True)
class KnowledgeBaseCounts:
    # Every row with the active model/revision: exactly what /ready counts.
    knowledge_base_rows: int
    # Of those, the rows that are this corpus's records, key and content.
    corpus_rows: int


def _verify_and_report(
    storage: Storage,
    result: ImportResult,
    records: list[dict[str, Any]],
    database_url: str,
    *,
    run_id: str,
    started_at: datetime,
    input_key: str,
    limit: int | None,
    skipped_by_checkpoint: bool,
    corpus_sha256: str,
    model_name: str,
    model_revision: str | None,
    table_name: str,
) -> ImportResult:
    # Asked of the database, not taken from the checkpoint. A checkpoint that
    # says "completed" only proves some earlier run finished against a target
    # with this id -- and a database rebuilt since, or a different one reached
    # through a tunnel on the same host:port/name, has the same id and none of
    # this corpus (or an older version of it). So every record is looked up by
    # its key and content, whether this run wrote it or skipped.
    corpus = _corpus_content_md5(records)
    counts = count_knowledge_base_rows(
        database_url,
        table_name,
        corpus,
        embedding_model=model_name,
        embedding_revision=model_revision,
    )
    unique_record_count = len(corpus)
    if not records:
        # Nothing was imported, so there is no corpus to name -- and a hash of
        # an empty list must never end up as a deployment's CORPUS_SHA256.
        status = "empty"
    elif counts.corpus_rows == unique_record_count:
        status = "completed"
    else:
        status = "incomplete"
    rows_outside_corpus = counts.knowledge_base_rows - counts.corpus_rows
    recorded_sha256 = None if status == "empty" else corpus_sha256
    report_key = f"{PIPELINE_REPORTS_PREFIX}/import_knowledge_base_{run_id}.json"
    write_json_report(
        storage,
        report_key,
        {
            "run_id": run_id,
            "stage": "import_knowledge_base",
            "status": status,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "input_key": input_key,
            "limit": limit,
            "skipped_by_checkpoint": skipped_by_checkpoint,
            "corpus_sha256": recorded_sha256,
            "record_count": result.attempted_count,
            "unique_record_count": unique_record_count,
            "affected_count": result.affected_count,
            "corpus_rows": counts.corpus_rows,
            "knowledge_base_rows": counts.knowledge_base_rows,
            "rows_outside_corpus": rows_outside_corpus,
            "embedding_model": model_name,
            "embedding_revision": model_revision,
            "table_name": table_name,
            # Host, port and database name only: a report is a file people
            # copy around, and the URL it came from may carry a password.
            "target_id": database_target_id(database_url),
        },
    )
    if status == "incomplete":
        raise KnowledgeBaseImportIncompleteError(
            f"{table_name} holds {counts.corpus_rows} of the "
            f"{unique_record_count} records this import covers (same key, "
            f"same content, embedded by {model_name} @ {model_revision}). "
            "The table does not hold what the import checkpoint says it "
            "does: a database rebuilt since, a different one on the same "
            "host:port/name, or another version of this corpus. Rerun with "
            "--reset-checkpoint (--reset-import-checkpoint for "
            f"run-wechat-pipeline). Report: {report_key}"
        )
    if rows_outside_corpus:
        # Not a failure: the loader upserts and never deletes, so a corpus
        # refresh that drops articles leaves their rows behind. But /ready
        # counts them and retrieval can return them, so CORPUS_SHA256 then
        # names only part of what is being served.
        logger.warning(
            "Knowledge base holds rows outside this corpus",
            extra={
                "event": "rows_outside_corpus",
                "stage": "import",
                "rows_outside_corpus": rows_outside_corpus,
                "knowledge_base_rows": counts.knowledge_base_rows,
                "corpus_sha256": recorded_sha256,
            },
        )

    return replace(
        result,
        corpus_sha256=recorded_sha256,
        knowledge_base_rows=counts.knowledge_base_rows,
        unique_record_count=unique_record_count,
        rows_outside_corpus=rows_outside_corpus,
        skipped_by_checkpoint=skipped_by_checkpoint,
        report_key=report_key,
    )


def _corpus_content_md5(
    records: list[dict[str, Any]],
) -> dict[tuple[str, str], str]:
    # Keyed like the table's unique index. A later record with the same key
    # wins, as it does in the table: the loader writes in order and upserts.
    return {
        (str(record["link"]), str(record["question_text"])): hashlib.md5(
            str(record["content"]).encode("utf-8"),
            usedforsecurity=False,
        ).hexdigest()
        for record in records
    }


def count_knowledge_base_rows(
    database_url: str,
    table_name: str,
    corpus: dict[tuple[str, str], str],
    *,
    embedding_model: str,
    embedding_revision: str | None,
) -> KnowledgeBaseCounts:
    connection = psycopg2.connect(
        database_url,
        connect_timeout=rag_config["pgvector"].get(
            "connect_timeout_seconds", 5
        ),
    )
    try:
        with connection.cursor() as cursor:
            return KnowledgeBaseCounts(
                knowledge_base_rows=count_active_rows(
                    cursor,
                    table_name,
                    embedding_model=embedding_model,
                    embedding_revision=embedding_revision,
                ),
                corpus_rows=count_corpus_rows(
                    cursor,
                    table_name,
                    corpus,
                    embedding_model=embedding_model,
                    embedding_revision=embedding_revision,
                ),
            )
    except UndefinedTable as error:
        # Reached when a completed checkpoint skipped the import against a
        # database that has not even been migrated.
        raise KnowledgeBaseImportIncompleteError(
            f"{table_name} does not exist in this database. Run `alembic "
            "upgrade head`, then rerun with --reset-checkpoint "
            "(--reset-import-checkpoint for run-wechat-pipeline)."
        ) from error
    finally:
        connection.close()


def database_target_id(database_url: str) -> str:
    parsed = urlparse(database_url)
    database_name = parsed.path.lstrip("/")
    if not parsed.hostname or not database_name:
        raise ValueError("database_url must include a host and database name")

    port = f":{parsed.port}" if parsed.port else ""
    return (
        f"{parsed.scheme}://{parsed.hostname}{port}/{database_name}"
    )
