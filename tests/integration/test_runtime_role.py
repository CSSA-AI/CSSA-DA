"""The API's runtime role, exercised against a real Postgres.

Local development and CI connect as a superuser, so nothing else in the test
suite would notice a code path that needs a privilege the production role
lacks. These tests provision the role exactly as production does and then
drive the real API code paths through it.
"""

import os
import secrets
from datetime import date, datetime, timezone
from urllib.parse import quote, urlparse, urlunparse
from uuid import uuid4

import numpy as np
import psycopg2
import pytest
from psycopg2 import errors, sql

from app.core.config import rag_config
from app.services.chat_interactions import (
    ChatInteractionRecord,
    record_chat_interaction,
)
from app.services.rag.model_registry import (
    ModelRegistryStatus,
    model_registry,
)
from app.services.readiness import check_readiness
from app.services.system_status import get_pipeline_metadata_status
from ops.provision_runtime_role import (
    ProvisioningError,
    provision_runtime_role,
)
from pipelines.loaders.postgres_knowledge_base import (
    PostgresKnowledgeBaseLoader,
)
from pipelines.loaders.postgres_pipeline_runs import (
    PipelineRunRecord,
    PostgresPipelineRunLoader,
)


pytestmark = pytest.mark.integration

if os.getenv("RUN_INTEGRATION_TESTS") != "1":
    pytest.skip("skip integration tests by default", allow_module_level=True)


class FakeEmbedder:
    def encode(self, texts, *, normalize_embeddings):
        return np.array([[0.1] * 384 for _ in texts])


@pytest.fixture
def runtime_role(test_database_url):
    # Roles are cluster-wide, unlike tables, so each test gets its own name
    # and removes it afterwards.
    role = f"cssa_app_it_{uuid4().hex[:8]}"
    yield role
    connection = psycopg2.connect(test_database_url)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname = %s;", (role,)
                )
                if cursor.fetchone():
                    cursor.execute(
                        sql.SQL("DROP OWNED BY {};").format(
                            sql.Identifier(role)
                        )
                    )
                    cursor.execute(
                        sql.SQL("DROP ROLE {};").format(sql.Identifier(role))
                    )
    finally:
        connection.close()


def _url_for(database_url, user, password):
    parsed = urlparse(database_url)
    netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@"
    netloc += parsed.hostname
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _provision(test_database_url, role):
    password = secrets.token_urlsafe(24)
    provision_runtime_role(test_database_url, role, password)
    return _url_for(test_database_url, role, password)


def _superuser_execute(test_database_url, statement, params=None):
    connection = psycopg2.connect(test_database_url)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(statement, params)
                if cursor.description:
                    return cursor.fetchall()
                return None
    finally:
        connection.close()


def _seed_active_row(test_database_url):
    retriever = rag_config["retriever"]
    with PostgresKnowledgeBaseLoader(
        test_database_url,
        rag_config["pgvector"]["table_name"],
        embedding_model=retriever["embedding_model"],
        embedding_revision=retriever.get("embedding_revision"),
        expected_embedding_dim=384,
    ) as loader:
        loader.load_batch(
            [
                {
                    "question_text": "How do I enrol?",
                    "content": "Enrol through my.unimelb.",
                    "source": "University of Melbourne",
                    "author": "integration-test",
                    "post_date": date(2026, 7, 4),
                    "language": "en",
                    "created_at": datetime(2026, 7, 4, tzinfo=timezone.utc),
                    "tags": ["enrolment"],
                    "link": "https://example.com/runtime-role",
                }
            ],
            [[0.1] * 384],
        )


def test_runtime_role_serves_every_api_code_path(
    test_database_url,
    runtime_role,
    monkeypatch,
):
    from app.services.rag.retriever.pg_retriever import PGVectorRetriever

    runtime_url = _provision(test_database_url, runtime_role)
    _seed_active_row(test_database_url)
    PostgresPipelineRunLoader(test_database_url).upsert_run(
        PipelineRunRecord(
            id="run-runtime-role",
            pipeline_name="wechat",
            status="completed",
            started_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
        )
    )
    monkeypatch.setattr(
        model_registry,
        "status",
        lambda: ModelRegistryStatus(embedding="ready", reranker="ready"),
    )
    monkeypatch.setattr(
        model_registry,
        "get_embedding_model",
        lambda: FakeEmbedder(),
    )

    readiness = check_readiness(runtime_url)
    assert readiness.is_ready
    assert readiness.knowledge_base_rows == 1

    retriever = PGVectorRetriever(database_url=runtime_url)
    try:
        results = retriever.search("How do I enrol?", top_k=1)
    finally:
        retriever.close()
    assert [result.article.link for result in results] == [
        "https://example.com/runtime-role"
    ]

    pipeline_status = get_pipeline_metadata_status(runtime_url)
    assert pipeline_status.reason is None
    assert pipeline_status.latest_run.status == "completed"

    # record_chat_interaction never raises -- a refused write is only logged --
    # so the proof is the row. This is the check that caught ON CONFLICT
    # needing SELECT on request_id.
    record_chat_interaction(
        ChatInteractionRecord(
            request_id="req-runtime-role",
            query="How do I enrol?",
            answer="Through my.unimelb.",
            retrieved=[],
            config={},
        ),
        database_url=runtime_url,
    )
    assert _superuser_execute(
        test_database_url,
        "SELECT COUNT(*) FROM chat_interactions WHERE request_id = %s;",
        ("req-runtime-role",),
    ) == [(1,)]


@pytest.mark.parametrize(
    "statement",
    [
        # What a migration does.
        "CREATE TABLE runtime_role_probe (id integer);",
        "ALTER TABLE knowledge_base ADD COLUMN probe integer;",
        "DROP TABLE chat_interactions;",
        "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
        # What only the corpus import does.
        "INSERT INTO knowledge_base (question_text, content) VALUES ('q', 'c');",
        "DELETE FROM knowledge_base;",
        # Reading back other people's questions.
        "SELECT query FROM chat_interactions;",
    ],
)
def test_runtime_role_cannot_do_what_the_migration_identity_does(
    test_database_url,
    runtime_role,
    statement,
):
    runtime_url = _provision(test_database_url, runtime_role)

    connection = psycopg2.connect(runtime_url)
    try:
        with pytest.raises(errors.InsufficientPrivilege):
            with connection.cursor() as cursor:
                cursor.execute(statement)
    finally:
        connection.rollback()
        connection.close()


def test_rerun_converges_privileges_and_rotates_the_password(
    test_database_url,
    runtime_role,
):
    first_password = secrets.token_urlsafe(24)
    first = provision_runtime_role(
        test_database_url, runtime_role, first_password
    )
    # Drift: someone grants a write by hand.
    _superuser_execute(
        test_database_url,
        sql.SQL("GRANT INSERT ON knowledge_base TO {};").format(
            sql.Identifier(runtime_role)
        ),
    )

    second_password = secrets.token_urlsafe(24)
    second = provision_runtime_role(
        test_database_url, runtime_role, second_password
    )

    assert first.created is True
    assert second.created is False
    assert _superuser_execute(
        test_database_url,
        "SELECT has_table_privilege(%s, 'knowledge_base', 'INSERT');",
        (runtime_role,),
    ) == [(False,)]
    with pytest.raises(psycopg2.OperationalError):
        psycopg2.connect(
            _url_for(test_database_url, runtime_role, first_password)
        ).close()
    psycopg2.connect(
        _url_for(test_database_url, runtime_role, second_password)
    ).close()


def test_refuses_to_repurpose_a_privileged_role(
    test_database_url,
    runtime_role,
):
    _superuser_execute(
        test_database_url,
        sql.SQL("CREATE ROLE {} LOGIN CREATEDB;").format(
            sql.Identifier(runtime_role)
        ),
    )

    with pytest.raises(ProvisioningError, match="rolcreatedb"):
        provision_runtime_role(
            test_database_url, runtime_role, secrets.token_urlsafe(24)
        )


def test_refuses_a_role_that_inherits_other_privileges(
    test_database_url,
    runtime_role,
):
    provision_runtime_role(
        test_database_url, runtime_role, secrets.token_urlsafe(24)
    )
    _superuser_execute(
        test_database_url,
        sql.SQL("GRANT pg_read_all_data TO {};").format(
            sql.Identifier(runtime_role)
        ),
    )

    with pytest.raises(ProvisioningError, match="member of"):
        provision_runtime_role(
            test_database_url, runtime_role, secrets.token_urlsafe(24)
        )


def test_refuses_to_provision_the_identity_it_is_connected_as(
    test_database_url,
):
    connected_as = urlparse(test_database_url).username

    with pytest.raises(ProvisioningError, match="connected as"):
        provision_runtime_role(
            test_database_url, connected_as, secrets.token_urlsafe(24)
        )
