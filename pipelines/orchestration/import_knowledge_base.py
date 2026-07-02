import argparse
import os
from pathlib import Path

from app.core.config import rag_config
from pipelines.embedding.knowledge_base_text import encode_records
from pipelines.loaders.postgres_knowledge_base import insert_records
from pipelines.shared.json_records import load_json_records
from pipelines.shared.paths import DEFAULT_KNOWLEDGE_BASE_INPUT
from pipelines.validation.knowledge_base_records import validate_records


def import_records(
    input_file: Path,
    database_url: str,
    *,
    model_name: str | None = None,
    table_name: str | None = None,
    limit: int | None = None,
) -> int:
    records = load_json_records(input_file)
    if limit is not None:
        records = records[:limit]

    errors = validate_records(records)
    if errors:
        for error in errors[:20]:
            print(f"- {error}")
        if len(errors) > 20:
            print(f"- ... {len(errors) - 20} more")
        raise ValueError(f"Refusing to import {len(errors)} validation errors")

    model_name = model_name or rag_config["retriever"]["embedding_model"]
    table_name = table_name or rag_config["pgvector"]["table_name"]

    print(f"Input file: {input_file}")
    print(f"Rows to import: {len(records)}")
    print(f"Embedding model: {model_name}")
    print(f"Target table: {table_name}")

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    embeddings = encode_records(records, model)
    inserted = insert_records(
        records,
        embeddings,
        database_url,
        table_name,
        expected_embedding_dim=rag_config["retriever"]["embedding_dim"],
    )

    print(f"Inserted rows: {inserted}")
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import validated knowledge-base records into Postgres."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_KNOWLEDGE_BASE_INPUT,
        help="Processed JSON file to import.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="Postgres connection URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Import only the first N rows. Useful for smoke tests.",
    )
    args = parser.parse_args()

    if not args.database_url:
        raise ValueError("DATABASE_URL is required")

    import_records(
        input_file=args.input,
        database_url=args.database_url,
        limit=args.limit,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
