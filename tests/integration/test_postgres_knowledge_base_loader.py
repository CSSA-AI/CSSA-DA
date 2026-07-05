import os
from datetime import date, datetime, timezone

import psycopg2
import pytest

from pipelines.loaders.postgres_knowledge_base import insert_records


pytestmark = pytest.mark.integration

if os.getenv("RUN_INTEGRATION_TESTS") != "1":
    pytest.skip("skip integration tests by default", allow_module_level=True)


TEST_EMBEDDING = [0.1] * 384
EMBEDDING_MODEL = "test-embedding-model"
EMBEDDING_REVISION = "revision-123"


def _knowledge_base_record():
    return {
        "question_text": "How do I apply for special consideration?",
        "content": "Apply through the university portal.",
        "source": "University of Melbourne",
        "author": "integration-test",
        "post_date": date(2026, 7, 1),
        "language": "en",
        "created_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
        "tags": ["unimelb", "special consideration"],
        "link": "https://example.com/special-consideration",
    }


def test_loader_inserts_knowledge_base_record(test_database_url):
    record = _knowledge_base_record()

    inserted = insert_records(
        records=[record],
        embeddings=[TEST_EMBEDDING],
        database_url=test_database_url,
        table_name="knowledge_base",
        embedding_model=EMBEDDING_MODEL,
        embedding_revision=EMBEDDING_REVISION,
        expected_embedding_dim=384,
    )

    with psycopg2.connect(test_database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT question_text, content, source, author, tags, link,
                       embedding_model, embedding_revision
                FROM knowledge_base
                """
            )
            stored = cur.fetchone()

    assert inserted == 1
    assert stored == (
        record["question_text"],
        record["content"],
        record["source"],
        record["author"],
        record["tags"],
        record["link"],
        EMBEDDING_MODEL,
        EMBEDDING_REVISION,
    )


def test_loader_ignores_duplicate_record(test_database_url):
    record = _knowledge_base_record()

    first_inserted = insert_records(
        records=[record],
        embeddings=[TEST_EMBEDDING],
        database_url=test_database_url,
        table_name="knowledge_base",
        embedding_model=EMBEDDING_MODEL,
        expected_embedding_dim=384,
    )
    second_inserted = insert_records(
        records=[record],
        embeddings=[TEST_EMBEDDING],
        database_url=test_database_url,
        table_name="knowledge_base",
        embedding_model=EMBEDDING_MODEL,
        expected_embedding_dim=384,
    )

    with psycopg2.connect(test_database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM knowledge_base;")
            row_count = cur.fetchone()[0]

    assert first_inserted == 1
    assert second_inserted == 0
    assert row_count == 1
