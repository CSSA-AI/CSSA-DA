import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2 import sql

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import rag_config, settings


@dataclass(frozen=True)
class EmbeddingGroup:
    embedding_model: str | None
    embedding_revision: str | None
    row_count: int


@dataclass(frozen=True)
class KnowledgeBaseStatus:
    database: str
    table: str
    table_exists: bool
    total_rows: int
    active_embedding_model: str
    active_embedding_revision: str | None
    active_rows: int
    embedding_groups: list[EmbeddingGroup]
    latest_created_at: str | None = None
    reason: str | None = None

    @property
    def is_ok(self) -> bool:
        return self.database == "ok" and self.table_exists

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "embedding_groups": [
                asdict(group) for group in self.embedding_groups
            ],
        }


def get_knowledge_base_status(
    database_url: str | None = None,
) -> KnowledgeBaseStatus:
    retriever_config = rag_config["retriever"]
    pgvector_config = rag_config["pgvector"]
    table_name = pgvector_config["table_name"]
    active_model = retriever_config["embedding_model"]
    active_revision = retriever_config.get("embedding_revision")
    database_url = database_url or settings.DATABASE_URL

    if not database_url:
        return KnowledgeBaseStatus(
            database="missing",
            table=table_name,
            table_exists=False,
            total_rows=0,
            active_embedding_model=active_model,
            active_embedding_revision=active_revision,
            active_rows=0,
            embedding_groups=[],
            reason="DATABASE_URL is not configured",
        )

    try:
        with psycopg2.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass(%s);", (table_name,))
                table_exists = cursor.fetchone()[0] is not None
                if not table_exists:
                    return KnowledgeBaseStatus(
                        database="ok",
                        table=table_name,
                        table_exists=False,
                        total_rows=0,
                        active_embedding_model=active_model,
                        active_embedding_revision=active_revision,
                        active_rows=0,
                        embedding_groups=[],
                        reason=f"{table_name} table does not exist",
                    )

                table = sql.Identifier(table_name)
                cursor.execute(
                    sql.SQL("""
                        SELECT COUNT(*)
                        FROM {table};
                    """).format(table=table)
                )
                total_rows = cursor.fetchone()[0]

                cursor.execute(
                    sql.SQL("""
                        SELECT COUNT(*)
                        FROM {table}
                        WHERE embedding_model = %s
                          AND embedding_revision IS NOT DISTINCT FROM %s;
                    """).format(table=table),
                    (active_model, active_revision),
                )
                active_rows = cursor.fetchone()[0]

                cursor.execute(
                    sql.SQL("""
                        SELECT embedding_model, embedding_revision, COUNT(*)
                        FROM {table}
                        GROUP BY embedding_model, embedding_revision
                        ORDER BY COUNT(*) DESC, embedding_model, embedding_revision;
                    """).format(table=table)
                )
                embedding_groups = [
                    EmbeddingGroup(
                        embedding_model=model,
                        embedding_revision=revision,
                        row_count=count,
                    )
                    for model, revision, count in cursor.fetchall()
                ]

                cursor.execute(
                    sql.SQL("""
                        SELECT MAX(created_at)
                        FROM {table};
                    """).format(table=table)
                )
                latest_created_at = cursor.fetchone()[0]
    except Exception as error:
        return KnowledgeBaseStatus(
            database="unavailable",
            table=table_name,
            table_exists=False,
            total_rows=0,
            active_embedding_model=active_model,
            active_embedding_revision=active_revision,
            active_rows=0,
            embedding_groups=[],
            reason=str(error),
        )

    return KnowledgeBaseStatus(
        database="ok",
        table=table_name,
        table_exists=True,
        total_rows=total_rows,
        active_embedding_model=active_model,
        active_embedding_revision=active_revision,
        active_rows=active_rows,
        embedding_groups=embedding_groups,
        latest_created_at=(
            latest_created_at.isoformat() if latest_created_at else None
        ),
    )


def print_human_status(status: KnowledgeBaseStatus) -> None:
    print(f"Database: {status.database}")
    print(f"Table: {status.table}")
    print(f"Table exists: {status.table_exists}")
    if status.reason:
        print(f"Reason: {status.reason}")
    print(f"Total rows: {status.total_rows}")
    print(f"Active rows: {status.active_rows}")
    print(f"Active embedding model: {status.active_embedding_model}")
    print(f"Active embedding revision: {status.active_embedding_revision}")
    print(f"Latest created_at: {status.latest_created_at}")

    if not status.embedding_groups:
        print("Embedding groups: none")
        return

    print("Embedding groups:")
    for group in status.embedding_groups:
        print(
            "- "
            f"{group.embedding_model} @ {group.embedding_revision}: "
            f"{group.row_count}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect PostgreSQL knowledge_base status."
    )
    parser.add_argument(
        "--database-url",
        default=settings.DATABASE_URL,
        help="Postgres connection URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    args = parser.parse_args()

    status = get_knowledge_base_status(args.database_url)
    if args.json:
        print(json.dumps(status.to_dict(), ensure_ascii=False, indent=2))
    else:
        print_human_status(status)

    return 0 if status.is_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
