"""What "the knowledge base has data" means, defined once.

/ready gates traffic on this count, the corpus import reports it, and
ops/db_status shows it. They have to agree to the row: after loading a corpus
the operator compares the import report's number against /ready's
(ROADMAP_platform item 20), and two spellings of the query would turn a real
mismatch into noise, or hide one.
"""

from typing import Any

from psycopg2 import sql


def count_active_rows(
    cursor: Any,
    table_name: str,
    *,
    embedding_model: str,
    embedding_revision: str | None,
) -> int:
    # Only rows embedded by this exact model and revision count. Vectors from
    # another model live in a different space (possibly a different dimension)
    # and are worse than none, so a table full of them reads as empty.
    cursor.execute(
        sql.SQL("""
            SELECT COUNT(*)
            FROM {table}
            WHERE embedding_model = %s
              AND embedding_revision IS NOT DISTINCT FROM %s;
        """).format(table=sql.Identifier(table_name)),
        (embedding_model, embedding_revision),
    )
    return cursor.fetchone()[0]
