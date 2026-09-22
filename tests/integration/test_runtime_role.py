"""The API's runtime role, exercised against a real Postgres, the RDS way.

Local development and CI connect as a superuser, so nothing else in the test
suite would notice a code path that needs a privilege the production role
lacks -- or a provisioning statement that only a superuser may run.

So these tests reproduce production's shape in a scratch database:

- a **migration identity** that is NOT a superuser, only CREATEROLE and
  CREATEDB, and owns the database -- like the RDS master user. It runs the
  migrations and the provisioning script;
- the **runtime role** that script creates, which then drives the real API
  code paths.

The superuser from TEST_DATABASE_URL only sets the stage (the vector
extension, as RDS preinstalls it for its master) and simulates drift someone
might introduce by hand.
"""

import os
import secrets
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlparse, urlunparse
from uuid import uuid4

import numpy as np
import psycopg2
import pytest
from alembic import command
from alembic.config import Config
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


PROJECT_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.integration

if os.getenv("RUN_INTEGRATION_TESTS") != "1":
    pytest.skip("skip integration tests by default", allow_module_level=True)


class FakeEmbedder:
    def encode(self, texts, *, normalize_embeddings):
        return np.array([[0.1] * 384 for _ in texts])


def _url_for(database_url, user, password, database=None):
    parsed = urlparse(database_url)
    netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@"
    netloc += parsed.hostname
    if parsed.port:
        netloc += f":{parsed.port}"
    path = f"/{database}" if database else parsed.path
    return urlunparse(parsed._replace(netloc=netloc, path=path))


def _execute(database_url, statement, params=None, *, autocommit=False):
    connection = psycopg2.connect(database_url)
    connection.autocommit = autocommit
    try:
        with connection.cursor() as cursor:
            cursor.execute(statement, params)
            rows = cursor.fetchall() if cursor.description else None
        if not autocommit:
            connection.commit()
        return rows
    finally:
        connection.close()


@pytest.fixture(scope="module")
def rds_like(test_database_url):
    """A scratch database owned by a non-superuser migration identity."""
    suffix = uuid4().hex[:8]
    migrator = f"migrator_{suffix}"
    migrator_password = secrets.token_urlsafe(24)
    database = f"runtime_role_{suffix}"

    _execute(
        test_database_url,
        sql.SQL(
            "CREATE ROLE {} LOGIN NOSUPERUSER CREATEROLE CREATEDB "
            "PASSWORD {};"
        ).format(sql.Identifier(migrator), sql.Literal(migrator_password)),
        autocommit=True,
    )
    _execute(
        test_database_url,
        sql.SQL("CREATE DATABASE {} OWNER {};").format(
            sql.Identifier(database), sql.Identifier(migrator)
        ),
        autocommit=True,
    )
    superuser_url = _url_for(
        test_database_url,
        urlparse(test_database_url).username,
        urlparse(test_database_url).password,
        database,
    )
    migrator_url = _url_for(
        test_database_url, migrator, migrator_password, database
    )
    # RDS preinstalls pgvector's availability for its master; here the
    # superuser creates it, so migration 0001's CREATE EXTENSION IF NOT
    # EXISTS is a no-op run by a non-superuser, as in production.
    _execute(superuser_url, "CREATE EXTENSION IF NOT EXISTS vector;")
    with patch.dict(os.environ, {"DATABASE_URL": migrator_url}):
        command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")

    yield {
        "migrator": migrator,
        "migrator_url": migrator_url,
        "superuser_url": superuser_url,
        "database": database,
    }

    _execute(
        test_database_url,
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid();",
        (database,),
        autocommit=True,
    )
    _execute(
        test_database_url,
        sql.SQL("DROP DATABASE {};").format(sql.Identifier(database)),
        autocommit=True,
    )
    _execute(
        test_database_url,
        sql.SQL("DROP ROLE {};").format(sql.Identifier(migrator)),
        autocommit=True,
    )


@pytest.fixture
def runtime_role(test_database_url, rds_like):
    # Roles are cluster-wide, unlike tables, so each test gets its own name
    # and removes it afterwards. DROP OWNED runs as the superuser: on
    # PostgreSQL 16 the migration identity holds ADMIN on the role it created
    # but not its privileges, so it could not do this itself.
    role = f"cssa_app_it_{uuid4().hex[:8]}"
    yield role
    for table in ("knowledge_base", "pipeline_runs", "chat_interactions"):
        _execute(rds_like["superuser_url"], f"DELETE FROM {table};")
    if _execute(
        test_database_url, "SELECT 1 FROM pg_roles WHERE rolname = %s;", (role,)
    ):
        _execute(
            rds_like["superuser_url"],
            sql.SQL("DROP OWNED BY {};").format(sql.Identifier(role)),
        )
        _execute(
            test_database_url,
            sql.SQL("DROP ROLE {};").format(sql.Identifier(role)),
            autocommit=True,
        )


def _provision(rds_like, role, password=None):
    password = password or secrets.token_urlsafe(24)
    result = provision_runtime_role(rds_like["migrator_url"], role, password)
    return result, _url_for(
        rds_like["migrator_url"], role, password, rds_like["database"]
    )


def _seed_active_row(database_url):
    retriever = rag_config["retriever"]
    with PostgresKnowledgeBaseLoader(
        database_url,
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


def _server_checks_passwords(rds_like, role):
    """False when pg_hba trusts this connection, so any password works."""
    try:
        psycopg2.connect(
            _url_for(
                rds_like["migrator_url"],
                role,
                "definitely-not-the-password",
                rds_like["database"],
            )
        ).close()
    except psycopg2.OperationalError:
        return True
    return False


def test_runtime_role_serves_every_api_code_path(rds_like, runtime_role, monkeypatch):
    from app.services.rag.retriever.pg_retriever import PGVectorRetriever

    _, runtime_url = _provision(rds_like, runtime_role)
    _seed_active_row(rds_like["migrator_url"])
    PostgresPipelineRunLoader(rds_like["migrator_url"]).upsert_run(
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
    assert _execute(
        rds_like["migrator_url"],
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
        "CREATE SCHEMA runtime_role_probe;",
        # What only the corpus import does. The explicit id keeps the
        # sequence out of it, so the table privilege is what refuses.
        "INSERT INTO knowledge_base (id, question_text, content) "
        "VALUES (-1, 'q', 'c');",
        "UPDATE knowledge_base SET content = 'poisoned';",
        "DELETE FROM knowledge_base;",
        # Reading back other people's questions.
        "SELECT query FROM chat_interactions;",
    ],
)
def test_runtime_role_cannot_do_what_the_migration_identity_does(
    rds_like,
    runtime_role,
    statement,
):
    _, runtime_url = _provision(rds_like, runtime_role)

    connection = psycopg2.connect(runtime_url)
    try:
        with pytest.raises(errors.InsufficientPrivilege):
            with connection.cursor() as cursor:
                cursor.execute(statement)
    finally:
        connection.rollback()
        connection.close()


def test_rerun_as_a_non_superuser_converges_and_rotates_the_password(
    rds_like,
    runtime_role,
):
    # This is the run that fails on RDS if the update path restates
    # NOSUPERUSER/NOREPLICATION/NOBYPASSRLS: every deploy after the first
    # would stop at the migrate task.
    first_password = secrets.token_urlsafe(24)
    first, _ = _provision(rds_like, runtime_role, first_password)
    # Drift: the owner grants a write by hand.
    _execute(
        rds_like["migrator_url"],
        sql.SQL("GRANT INSERT ON knowledge_base TO {};").format(
            sql.Identifier(runtime_role)
        ),
    )
    verifier_before = _execute(
        rds_like["superuser_url"],
        "SELECT rolpassword FROM pg_authid WHERE rolname = %s;",
        (runtime_role,),
    )

    second_password = secrets.token_urlsafe(24)
    second, second_url = _provision(rds_like, runtime_role, second_password)
    third, _ = _provision(rds_like, runtime_role, second_password)

    assert (first.created, second.created, third.created) == (
        True,
        False,
        False,
    )
    assert _execute(
        rds_like["migrator_url"],
        "SELECT has_table_privilege(%s, 'knowledge_base', 'INSERT');",
        (runtime_role,),
    ) == [(False,)]
    assert (
        _execute(
            rds_like["superuser_url"],
            "SELECT rolpassword FROM pg_authid WHERE rolname = %s;",
            (runtime_role,),
        )
        != verifier_before
    )
    psycopg2.connect(second_url).close()
    if _server_checks_passwords(rds_like, runtime_role):
        with pytest.raises(psycopg2.OperationalError):
            psycopg2.connect(
                _url_for(
                    rds_like["migrator_url"],
                    runtime_role,
                    first_password,
                    rds_like["database"],
                )
            ).close()


def test_a_grant_to_public_is_reported_not_ignored(rds_like, runtime_role):
    _provision(rds_like, runtime_role)
    _execute(
        rds_like["migrator_url"],
        "GRANT SELECT ON chat_interactions TO PUBLIC;",
    )
    try:
        with pytest.raises(
            ProvisioningError,
            match="has SELECT on chat_interactions",
        ):
            _provision(rds_like, runtime_role)
    finally:
        _execute(
            rds_like["migrator_url"],
            "REVOKE SELECT ON chat_interactions FROM PUBLIC;",
        )


def test_a_relation_owned_by_the_role_is_reported(rds_like, runtime_role):
    _provision(rds_like, runtime_role)
    _execute(
        rds_like["superuser_url"],
        sql.SQL(
            "CREATE TABLE runtime_role_owned (id integer); "
            "ALTER TABLE runtime_role_owned OWNER TO {};"
        ).format(sql.Identifier(runtime_role)),
    )
    try:
        with pytest.raises(
            ProvisioningError,
            match="owns relation public.runtime_role_owned",
        ):
            _provision(rds_like, runtime_role)
    finally:
        _execute(rds_like["superuser_url"], "DROP TABLE runtime_role_owned;")


def test_a_table_owned_by_someone_else_does_not_abort_the_run(
    test_database_url,
    rds_like,
    runtime_role,
):
    # e.g. a future pipeline role's table. The migration identity has no
    # rights on it, so REVOKE there would be an error; the run must skip it
    # and still verify it.
    other = f"other_owner_{uuid4().hex[:8]}"
    _execute(
        test_database_url,
        sql.SQL("CREATE ROLE {} NOLOGIN;").format(sql.Identifier(other)),
        autocommit=True,
    )
    _execute(
        rds_like["superuser_url"],
        sql.SQL(
            "CREATE TABLE runtime_role_foreign (id integer); "
            "ALTER TABLE runtime_role_foreign OWNER TO {};"
        ).format(sql.Identifier(other)),
    )
    try:
        _provision(rds_like, runtime_role)
        _provision(rds_like, runtime_role)
    finally:
        _execute(rds_like["superuser_url"], "DROP TABLE runtime_role_foreign;")
        _execute(
            test_database_url,
            sql.SQL("DROP ROLE {};").format(sql.Identifier(other)),
            autocommit=True,
        )


def test_refuses_to_repurpose_a_privileged_role(
    test_database_url,
    rds_like,
    runtime_role,
):
    _execute(
        test_database_url,
        sql.SQL("CREATE ROLE {} LOGIN CREATEDB;").format(
            sql.Identifier(runtime_role)
        ),
        autocommit=True,
    )

    with pytest.raises(ProvisioningError, match="rolcreatedb"):
        _provision(rds_like, runtime_role)


def test_refuses_a_role_that_inherits_other_privileges(
    test_database_url,
    rds_like,
    runtime_role,
):
    _provision(rds_like, runtime_role)
    _execute(
        test_database_url,
        sql.SQL("GRANT pg_read_all_data TO {};").format(
            sql.Identifier(runtime_role)
        ),
        autocommit=True,
    )

    with pytest.raises(ProvisioningError, match="member of"):
        _provision(rds_like, runtime_role)


def test_refuses_to_provision_the_identity_it_is_connected_as(rds_like):
    with pytest.raises(ProvisioningError, match="connected as"):
        provision_runtime_role(
            rds_like["migrator_url"],
            rds_like["migrator"],
            secrets.token_urlsafe(24),
        )
