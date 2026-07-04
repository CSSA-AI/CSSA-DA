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

    errors = validate_records(records)
    if errors:
        raise KnowledgeBaseValidationError(errors)

    if not records:
        return ImportResult(attempted_count=0, inserted_count=0)

    inserted_count = 0
    for start in range(0, len(records), batch_size):
        batch = records[start : start + batch_size]
        embeddings = encode_records(batch, embedder)
        inserted_count += loader.insert_batch(batch, embeddings)

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

    if not records:
        return ImportResult(attempted_count=0, inserted_count=0)

    errors = validate_records(records)
    if errors:
        raise KnowledgeBaseValidationError(errors)

    model_name = model_name or rag_config["retriever"]["embedding_model"]
    table_name = table_name or rag_config["pgvector"]["table_name"]

    from sentence_transformers import SentenceTransformer

    embedder = SentenceTransformer(model_name)
    with PostgresKnowledgeBaseLoader(
        database_url,
        table_name,
        expected_embedding_dim=rag_config["retriever"]["embedding_dim"],
    ) as loader:
        return import_knowledge_base(
            records,
            embedder,
            loader,
            batch_size=batch_size,
        )
