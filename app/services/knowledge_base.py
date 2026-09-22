"""What "the knowledge base has data" means, defined once.

/ready gates traffic on these counts, the corpus import reports them, and
ops/db_status shows them. They have to agree to the row: after loading a corpus
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


def count_corpus_rows(
    cursor: Any,
    table_name: str,
    corpus: dict[tuple[str, str], str],
    *,
    embedding_model: str,
    embedding_revision: str | None,
) -> int:
    """How many of a corpus's records the table holds, exactly as given.

    `corpus` maps each (link, question_text) -- the table's unique key -- to
    the md5 of the content stored under it. A row counts only if its key is in
    the corpus, its content is byte-for-byte that content, and it carries the
    active model/revision (the same filter as count_active_rows). Key and
    content are what the embedding is computed from, so a match means the row
    serves exactly what this corpus says.

    md5(text) hashes the server-encoded bytes; this assumes a UTF8 database,
    which RDS and the local pgvector image both default to.
    """
    if not corpus:
        return 0
    links, questions, content_md5s = zip(
        *((link, question, md5) for (link, question), md5 in corpus.items())
    )
    cursor.execute(
        sql.SQL("""
            SELECT COUNT(*)
            FROM {table} AS kb
            JOIN unnest(%s::text[], %s::text[], %s::text[])
              AS corpus(link, question_text, content_md5)
              ON kb.link = corpus.link
             AND kb.question_text = corpus.question_text
            WHERE kb.embedding_model = %s
              AND kb.embedding_revision IS NOT DISTINCT FROM %s
              AND md5(kb.content) = corpus.content_md5;
        """).format(table=sql.Identifier(table_name)),
        (
            list(links),
            list(questions),
            list(content_md5s),
            embedding_model,
            embedding_revision,
        ),
    )
    return cursor.fetchone()[0]
