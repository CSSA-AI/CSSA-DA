import os
from datetime import date, datetime, timezone

import numpy as np
import psycopg2
import pytest

from pipelines.loaders.postgres_knowledge_base import (
    PostgresKnowledgeBaseLoader,
)
from pipelines.orchestration.import_knowledge_base import (
    ImportResult,
    build_import_checkpoint_identity,
    database_target_id,
    import_knowledge_base,
)
from pipelines.shared.import_checkpoint import (
    MemoryImportCheckpointStore,
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

    with PostgresKnowledgeBaseLoader(
        test_database_url,
        "knowledge_base",
        embedding_model="fake-embedder",
        embedding_revision="revision-123",
        expected_embedding_dim=384,
    ) as loader:
        result = import_knowledge_base(
            records=[record],
            embedder=embedder,
            loader=loader,
        )

    with psycopg2.connect(test_database_url) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT question_text, content, tags, link,
                       embedding_model, embedding_revision
                FROM knowledge_base
                """
            )
            stored = cursor.fetchone()

    assert result == ImportResult(attempted_count=1, affected_count=1)
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
        "fake-embedder",
        "revision-123",
    )


def test_batched_import_is_idempotent(test_database_url):
    records = [_record(1), _record(2)]
    embedder = FakeEmbedder()

    with PostgresKnowledgeBaseLoader(
        test_database_url,
        "knowledge_base",
        embedding_model="fake-embedder",
        expected_embedding_dim=384,
    ) as loader:
        first_result = import_knowledge_base(
            records=records,
            embedder=embedder,
            loader=loader,
            batch_size=1,
        )
        second_result = import_knowledge_base(
            records=records,
            embedder=FakeEmbedder(),
            loader=loader,
            batch_size=1,
        )

    with psycopg2.connect(test_database_url) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM knowledge_base")
            row_count = cursor.fetchone()[0]

    assert first_result == ImportResult(
        attempted_count=2,
        affected_count=2,
    )
    assert second_result == ImportResult(
        attempted_count=2,
        affected_count=0,
    )
    assert len(embedder.encoded_batches) == 2
    assert row_count == 2


def test_failed_import_resumes_after_last_committed_batch(
    test_database_url,
):
    records = [_record(1), _record(2), _record(3)]
    checkpoint_store = MemoryImportCheckpointStore()
    identity = build_import_checkpoint_identity(
        records,
        model_name="fake-embedder",
        table_name="knowledge_base",
        target_id=database_target_id(test_database_url),
        batch_size=2,
    )

    with PostgresKnowledgeBaseLoader(
        test_database_url,
        "knowledge_base",
        embedding_model="fake-embedder",
        expected_embedding_dim=384,
    ) as postgres_loader:
        failing_loader = _FailOnSecondBatchLoader(postgres_loader)

        with pytest.raises(RuntimeError, match="simulated batch failure"):
            import_knowledge_base(
                records=records,
                embedder=FakeEmbedder(),
                loader=failing_loader,
                batch_size=2,
                checkpoint_store=checkpoint_store,
                checkpoint_identity=identity,
            )

        resumed_embedder = FakeEmbedder()
        result = import_knowledge_base(
            records=records,
            embedder=resumed_embedder,
            loader=postgres_loader,
            batch_size=2,
            checkpoint_store=checkpoint_store,
            checkpoint_identity=identity,
        )

    with psycopg2.connect(test_database_url) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM knowledge_base")
            row_count = cursor.fetchone()[0]

    assert result == ImportResult(
        attempted_count=3,
        affected_count=3,
    )
    assert len(resumed_embedder.encoded_batches) == 1
    assert len(resumed_embedder.encoded_batches[0]) == 1
    assert checkpoint_store.load().status == "completed"
    assert row_count == 3


class _FailOnSecondBatchLoader:
    def __init__(self, loader):
        self.loader = loader
        self.call_count = 0

    def load_batch(self, records, embeddings):
        self.call_count += 1
        if self.call_count == 2:
            raise RuntimeError("simulated batch failure")
        return self.loader.load_batch(records, embeddings)
