from dataclasses import dataclass
from typing import Any

import psycopg2
from psycopg2 import sql

from app.core.config import rag_config, settings


@dataclass(frozen=True)
class ReadinessCheck:
    status: str
    database: str
    knowledge_base_rows: int
    embedding_model: str
    embedding_revision: str | None
    reason: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "database": self.database,
            "knowledge_base_rows": self.knowledge_base_rows,
            "embedding_model": self.embedding_model,
            "embedding_revision": self.embedding_revision,
        }
        if self.reason:
            payload["reason"] = self.reason
        return payload


def check_readiness(database_url: str | None = None) -> ReadinessCheck:
    retriever_config = rag_config["retriever"]
    pgvector_config = rag_config["pgvector"]
    embedding_model = retriever_config["embedding_model"]
    embedding_revision = retriever_config.get("embedding_revision")
    table_name = pgvector_config["table_name"]
    database_url = database_url or settings.DATABASE_URL

    if not database_url:
        return ReadinessCheck(
            status="not_ready",
            database="missing",
            knowledge_base_rows=0,
            embedding_model=embedding_model,
            embedding_revision=embedding_revision,
            reason="DATABASE_URL is not configured",
        )

    try:
        with psycopg2.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                cursor.execute("SELECT to_regclass(%s);", (table_name,))
                if cursor.fetchone()[0] is None:
                    return ReadinessCheck(
                        status="not_ready",
                        database="ok",
                        knowledge_base_rows=0,
                        embedding_model=embedding_model,
                        embedding_revision=embedding_revision,
                        reason=f"{table_name} table does not exist",
                    )

                cursor.execute(
                    sql.SQL("""
                        SELECT COUNT(*)
                        FROM {table}
                        WHERE embedding_model = %s
                          AND embedding_revision IS NOT DISTINCT FROM %s;
                    """).format(table=sql.Identifier(table_name)),
                    (embedding_model, embedding_revision),
                )
                row_count = cursor.fetchone()[0]
    except Exception as error:
        return ReadinessCheck(
            status="not_ready",
            database="unavailable",
            knowledge_base_rows=0,
            embedding_model=embedding_model,
            embedding_revision=embedding_revision,
            reason=str(error),
        )

    if row_count == 0:
        return ReadinessCheck(
            status="not_ready",
            database="ok",
            knowledge_base_rows=0,
            embedding_model=embedding_model,
            embedding_revision=embedding_revision,
            reason=(
                "knowledge_base has no rows for the active embedding "
                "model/revision"
            ),
        )

    return ReadinessCheck(
        status="ready",
        database="ok",
        knowledge_base_rows=row_count,
        embedding_model=embedding_model,
        embedding_revision=embedding_revision,
    )
