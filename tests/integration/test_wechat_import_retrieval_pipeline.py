import os
from datetime import date

import numpy as np
import psycopg2
import pytest
from psycopg2.pool import ThreadedConnectionPool

from app.services.rag.retriever.pg_retriever import PGVectorRetriever
from pipelines.loaders.postgres_knowledge_base import (
    PostgresKnowledgeBaseLoader,
)
from pipelines.orchestration.import_knowledge_base import (
    ImportResult,
    import_knowledge_base,
)
from pipelines.transform.wechat_articles import transform_articles


pytestmark = pytest.mark.integration

if os.getenv("RUN_INTEGRATION_TESTS") != "1":
    pytest.skip("skip integration tests by default", allow_module_level=True)


TEST_EMBEDDING = [0.1] * 384
EMBEDDING_MODEL = "wechat-test-embedding-model"
EMBEDDING_REVISION = "revision-123"


class FakeEmbeddingModel:
    def encode(self, texts, *, normalize_embeddings=True):
        assert normalize_embeddings is True
        return np.array([TEST_EMBEDDING for _ in texts])


def test_wechat_transform_import_and_retrieve(test_database_url):
    transform_result = transform_articles(
        [
            {
                "title": "墨尔本校招指南",
                "content": (
                    "墨尔本校招指南正文内容，包含投递时间、简历准备、"
                    "面试安排、企业宣讲会和留学生求职注意事项。"
                ),
                "date": "2026-07-08",
                "link": "https://example.com/wechat/career-guide",
                "is_valid_for_rag": True,
            }
        ],
        created_at=date(2026, 7, 8),
    )
    records = transform_result.records

    with PostgresKnowledgeBaseLoader(
        test_database_url,
        "knowledge_base",
        embedding_model=EMBEDDING_MODEL,
        embedding_revision=EMBEDDING_REVISION,
        expected_embedding_dim=384,
    ) as loader:
        import_result = import_knowledge_base(
            records=records,
            embedder=FakeEmbeddingModel(),
            loader=loader,
        )

    retriever = PGVectorRetriever.__new__(PGVectorRetriever)
    retriever.pool = ThreadedConnectionPool(
        minconn=1,
        maxconn=1,
        dsn=test_database_url,
    )
    retriever.table_name = "knowledge_base"
    retriever.model_name = EMBEDDING_MODEL
    retriever.model_revision = EMBEDDING_REVISION
    retriever.model = FakeEmbeddingModel()

    try:
        results = retriever.search("墨尔本校招", top_k=3)
    finally:
        retriever.close()

    assert transform_result.stats.output_count == 1
    assert import_result == ImportResult(
        attempted_count=1,
        affected_count=1,
    )
    assert len(results) == 1
    assert results[0].article.questions == ["墨尔本校招指南"]
    assert "留学生求职注意事项" in results[0].article.text
    assert results[0].article.link == "https://example.com/wechat/career-guide"
