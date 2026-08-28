import os
from pathlib import Path
from unittest.mock import patch

import psycopg2
import pytest
from alembic import command
from alembic.config import Config


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def test_database_url():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.fail(
            "TEST_DATABASE_URL is required when RUN_INTEGRATION_TESTS=1"
        )
    return database_url


@pytest.fixture(scope="session")
def migrated_test_database(test_database_url):
    alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))

    with patch.dict(os.environ, {"DATABASE_URL": test_database_url}):
        command.upgrade(alembic_config, "head")


@pytest.fixture(scope="function", autouse=True)
def clean_knowledge_base(test_database_url, migrated_test_database):
    with psycopg2.connect(test_database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM knowledge_base;")
            cur.execute("DELETE FROM pipeline_runs;")
            cur.execute("DELETE FROM chat_interactions;")
        conn.commit()
