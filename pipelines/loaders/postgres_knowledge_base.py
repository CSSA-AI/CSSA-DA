import json
from typing import Any

import psycopg2
from psycopg2 import sql


def insert_records(
    records: list[dict[str, Any]],
    embeddings: list[list[float]],
    database_url: str,
    table_name: str,
    *,
    expected_embedding_dim: int | None = None,
) -> int:
    if len(records) != len(embeddings):
        raise ValueError(
            "records and embeddings must contain the same number of items"
        )

    if not records:
        return 0

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

    insert_sql = sql.SQL("""
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

    rows = []
    for record, embedding in zip(records, embeddings):
        rows.append(
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
        )

    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.executemany(insert_sql, rows)
            inserted = cur.rowcount
        conn.commit()

    return inserted
