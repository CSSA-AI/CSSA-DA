import os

import psycopg2
import pytest
from psycopg2.extras import Json

from app.core.config import rag_config
from app.services.readiness import check_readiness


pytestmark = pytest.mark.integration

if os.getenv("RUN_INTEGRATION_TESTS") != "1":
    pytest.skip("skip integration tests by default", allow_module_level=True)


def test_readiness_reports_not_ready_when_knowledge_base_is_empty(
    test_database_url,
):
    result = check_readiness(test_database_url)

    assert result.status == "not_ready"
    assert result.database == "ok"
    assert result.knowledge_base_rows == 0


def test_readiness_reports_ready_for_active_embedding_provenance(
    test_database_url,
):
    retriever_config = rag_config["retriever"]

    with psycopg2.connect(test_database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO knowledge_base (
                    question_text,
                    content,
                    link,
                    tags,
                    embedding_model,
                    embedding_revision,
                    embedding
                )
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s::vector);
                """,
                (
                    "墨尔本校招怎么准备？",
                    "准备简历、投递时间表和面试计划。",
                    "https://example.com/career",
                    Json(["career"]),
                    retriever_config["embedding_model"],
                    retriever_config.get("embedding_revision"),
                    [0.1] * retriever_config["embedding_dim"],
                ),
            )
        conn.commit()

    result = check_readiness(test_database_url)

    assert result.status == "ready"
    assert result.database == "ok"
    assert result.knowledge_base_rows == 1
