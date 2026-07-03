import os
from datetime import date, datetime, timezone

import numpy as np
import psycopg2
import pytest

from pipelines.orchestration.import_knowledge_base import (
    ImportResult,
    import_knowledge_base,
)


pytestmark = pytest.mark.integration

if os.getenv("RUN_INTEGRATION_TESTS") != "1":
    pytest.skip("skip integration tests by default", allow_module_level=True)


class FakeEmbedder:
    def __init__(self):
        self.encoded_texts = []
        self.encoded_batches = []

    def encode(self, texts, *, normalize_embeddings):
        assert normalize_embeddings is True
        self.encoded_texts.extend(texts)
        self.encoded_batches.append(texts)
        return np.array([[0.1] * 384 for _ in texts])


def _record(index=1):
    return {
        "question_text": (
            f"How do I apply for special consideration? {index}"
        ),
        "content": "Apply through the university portal.",
        "source": "University of Melbourne",
        "author": "integration-test",
        "post_date": date(2026, 7, 4),
        "language": "en",
        "created_at": datetime(2026, 7, 4, tzinfo=timezone.utc),
        "tags": ["unimelb", "special consideration"],
        "link": f"https://example.com/import-pipeline/{index}",
    }


def test_import_pipeline_validates_embeds_and_loads(test_database_url):
    record = _record()
    embedder = FakeEmbedder()

    result = import_knowledge_base(
        records=[record],
        embedder=embedder,
        database_url=test_database_url,
    )

    with psycopg2.connect(test_database_url) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT question_text, content, tags, link
                FROM knowledge_base
                """
            )
            stored = cursor.fetchone()

    assert result == ImportResult(attempted_count=1, inserted_count=1)
    assert embedder.encoded_texts == [
        (
            "How do I apply for special consideration? 1\n\n"
            "Apply through the university portal."
        )
    ]
    assert stored == (
        record["question_text"],
        record["content"],
        record["tags"],
        record["link"],
    )


def test_batched_import_is_idempotent(test_database_url):
    records = [_record(1), _record(2)]
    embedder = FakeEmbedder()

    first_result = import_knowledge_base(
        records=records,
        embedder=embedder,
        database_url=test_database_url,
        batch_size=1,
    )
    second_result = import_knowledge_base(
        records=records,
        embedder=FakeEmbedder(),
        database_url=test_database_url,
        batch_size=1,
    )

    with psycopg2.connect(test_database_url) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM knowledge_base")
            row_count = cursor.fetchone()[0]

    assert first_result == ImportResult(
        attempted_count=2,
        inserted_count=2,
    )
    assert second_result == ImportResult(
        attempted_count=2,
        inserted_count=0,
    )
    assert len(embedder.encoded_batches) == 2
    assert row_count == 2
