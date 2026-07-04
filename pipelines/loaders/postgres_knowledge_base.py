import json
from types import TracebackType
from typing import Any

import psycopg2
from psycopg2 import sql


class PostgresKnowledgeBaseLoader:
    def __init__(
        self,
        database_url: str,
        table_name: str,
        *,
        expected_embedding_dim: int | None = None,
    ):
        self.database_url = database_url
        self.table_name = table_name
        self.expected_embedding_dim = expected_embedding_dim
        self.connection = None

    def __enter__(self) -> "PostgresKnowledgeBaseLoader":
        self.connection = psycopg2.connect(self.database_url)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def insert_batch(
        self,
        records: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> int:
        _validate_batch(
            records,
            embeddings,
            self.expected_embedding_dim,
        )
        if not records:
            return 0
        if self.connection is None:
            raise RuntimeError(
                "PostgresKnowledgeBaseLoader must be used as a context manager"
            )

        insert_sql = _build_insert_sql(self.table_name)
        rows = _build_rows(records, embeddings)

        try:
            with self.connection.cursor() as cursor:
                cursor.executemany(insert_sql, rows)
                inserted = cursor.rowcount
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

        return inserted


def insert_records(
    records: list[dict[str, Any]],
    embeddings: list[list[float]],
    database_url: str,
    table_name: str,
    *,
    expected_embedding_dim: int | None = None,
) -> int:
    _validate_batch(records, embeddings, expected_embedding_dim)
    if not records:
        return 0

    with PostgresKnowledgeBaseLoader(
        database_url,
        table_name,
        expected_embedding_dim=expected_embedding_dim,
    ) as loader:
        return loader.insert_batch(records, embeddings)


def _validate_batch(
    records: list[dict[str, Any]],
    embeddings: list[list[float]],
    expected_embedding_dim: int | None,
) -> None:
    if len(records) != len(embeddings):
        raise ValueError(
            "records and embeddings must contain the same number of items"
        )

    if not records:
        return

    embedding_dims = []
    for index, embedding in enumerate(embeddings, start=1):
        if len(embedding) == 0:
            raise ValueError(f"embedding {index} is empty")
        embedding_dims.append(len(embedding))

    if len(set(embedding_dims)) != 1:
        raise ValueError("all embeddings must have the same dimension")

    if (
        expected_embedding_dim is not None
        and embedding_dims[0] != expected_embedding_dim
    ):
        raise ValueError(
            f"expected {expected_embedding_dim}-dimensional embeddings, "
            f"received {embedding_dims[0]}"
        )


def _build_insert_sql(table_name: str):
    return sql.SQL("""
        INSERT INTO {table_name} (
            question_text,
            content,
            source,
            author,
            post_date,
            language,
            created_at,
            tags,
            link,
            embedding
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::vector
        )
        ON CONFLICT (link, question_text) DO NOTHING
    """).format(table_name=sql.Identifier(table_name))


def _build_rows(
    records: list[dict[str, Any]],
    embeddings: list[list[float]],
) -> list[tuple[Any, ...]]:
    return [
        (
            record["question_text"],
            record["content"],
            record.get("source"),
            record.get("author"),
            record.get("post_date"),
            record.get("language"),
            record.get("created_at"),
            json.dumps(record.get("tags", []), ensure_ascii=False),
            record.get("link"),
            embedding,
        )
        for record, embedding in zip(records, embeddings)
    ]
