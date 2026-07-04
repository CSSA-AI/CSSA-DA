import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.core.config import rag_config
from pipelines.embedding.knowledge_base_text import encode_records
from pipelines.loaders.base import KnowledgeBaseLoader
from pipelines.loaders.postgres_knowledge_base import (
    PostgresKnowledgeBaseLoader,
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
) -> ImportResult:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    _validate_import_records(records)
    return _import_validated_records(
        records,
        embedder,
        loader,
        batch_size=batch_size,
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
) -> ImportResult:
    if not records:
        return ImportResult(attempted_count=0, inserted_count=0)

    inserted_count = 0
    batch_count = math.ceil(len(records) / batch_size)
    for batch_index, start in enumerate(
        range(0, len(records), batch_size),
        start=1,
    ):
        batch = records[start : start + batch_size]
        logger.info(
            "Import batch started",
            extra={
                "event": "batch_started",
                "stage": "import",
                "batch_number": batch_index,
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
                    "batch_number": batch_index,
                    "batch_count": batch_count,
                    "record_count": len(batch),
                    "error_type": type(error).__name__,
                },
            )
            raise
        inserted_count += batch_inserted_count
        logger.info(
            "Import batch completed",
            extra={
                "event": "batch_completed",
                "stage": "import",
                "batch_number": batch_index,
                "batch_count": batch_count,
                "record_count": len(batch),
                "inserted_count": batch_inserted_count,
            },
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
) -> ImportResult:
    if limit is not None and limit < 0:
        raise ValueError("limit cannot be negative")
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    records = load_json_records(input_file)
    if limit is not None:
        records = records[:limit]

    _validate_import_records(records)
    if not records:
        return ImportResult(attempted_count=0, inserted_count=0)

    model_name = model_name or rag_config["retriever"]["embedding_model"]
    table_name = table_name or rag_config["pgvector"]["table_name"]

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
        )
