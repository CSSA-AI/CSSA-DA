from unittest.mock import MagicMock, patch

import pytest

from pipelines.loaders.postgres_knowledge_base import (
    PostgresKnowledgeBaseLoader,
    insert_records,
)


DATABASE_URL = "postgresql://test:test@localhost:5432/testdb"
TABLE_NAME = "knowledge_base"
EMBEDDING_MODEL = "test-embedding-model"
EMBEDDING_REVISION = "revision-123"


def _record(index=1):
    return {
        "question_text": f"Question {index}",
        "content": f"Content {index}",
        "tags": ["test"],
        "link": f"https://example.com/{index}",
    }


@patch("pipelines.loaders.postgres_knowledge_base.psycopg2.connect")
def test_empty_batch_returns_zero_without_connecting(mock_connect):
    affected = insert_records(
        [],
        [],
        DATABASE_URL,
        TABLE_NAME,
        embedding_model=EMBEDDING_MODEL,
    )

    assert affected == 0
    mock_connect.assert_not_called()


@patch("pipelines.loaders.postgres_knowledge_base.psycopg2.connect")
def test_rejects_mismatched_record_and_embedding_counts(mock_connect):
    with pytest.raises(ValueError, match="same number of items"):
        insert_records(
            [{}],
            [],
            DATABASE_URL,
            TABLE_NAME,
            embedding_model=EMBEDDING_MODEL,
        )

    mock_connect.assert_not_called()


@patch("pipelines.loaders.postgres_knowledge_base.psycopg2.connect")
def test_rejects_empty_embedding(mock_connect):
    with pytest.raises(ValueError, match="embedding 1 is empty"):
        insert_records(
            [{}],
            [[]],
            DATABASE_URL,
            TABLE_NAME,
            embedding_model=EMBEDDING_MODEL,
        )

    mock_connect.assert_not_called()


@patch("pipelines.loaders.postgres_knowledge_base.psycopg2.connect")
def test_rejects_inconsistent_embedding_dimensions(mock_connect):
    with pytest.raises(ValueError, match="same dimension"):
        insert_records(
            [{}, {}],
            [[0.1, 0.2], [0.1]],
            DATABASE_URL,
            TABLE_NAME,
            embedding_model=EMBEDDING_MODEL,
        )

    mock_connect.assert_not_called()


@patch("pipelines.loaders.postgres_knowledge_base.psycopg2.connect")
def test_rejects_unexpected_embedding_dimension(mock_connect):
    with pytest.raises(ValueError, match="expected 384-dimensional"):
        insert_records(
            [{}],
            [[0.1, 0.2]],
            DATABASE_URL,
            TABLE_NAME,
            embedding_model=EMBEDDING_MODEL,
            expected_embedding_dim=384,
        )

    mock_connect.assert_not_called()


@patch("pipelines.loaders.postgres_knowledge_base.psycopg2.connect")
def test_context_loader_reuses_one_connection_for_batches(mock_connect):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.rowcount = 1
    mock_connect.return_value = connection

    with PostgresKnowledgeBaseLoader(
        DATABASE_URL,
        TABLE_NAME,
        embedding_model=EMBEDDING_MODEL,
        embedding_revision=EMBEDDING_REVISION,
        expected_embedding_dim=2,
    ) as loader:
        first_affected = loader.insert_batch(
            [_record(1)],
            [[0.1, 0.2]],
        )
        second_affected = loader.insert_batch(
            [_record(2)],
            [[0.3, 0.4]],
        )

    assert first_affected == 1
    assert second_affected == 1
    mock_connect.assert_called_once_with(DATABASE_URL)
    assert cursor.executemany.call_count == 2
    first_row = cursor.executemany.call_args_list[0].args[1][0]
    assert first_row[-3:] == (
        EMBEDDING_MODEL,
        EMBEDDING_REVISION,
        [0.1, 0.2],
    )
    assert connection.commit.call_count == 2
    connection.close.assert_called_once_with()


@patch("pipelines.loaders.postgres_knowledge_base.psycopg2.connect")
def test_context_loader_rolls_back_failed_batch(mock_connect):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.executemany.side_effect = OSError("database unavailable")
    mock_connect.return_value = connection

    with (
        PostgresKnowledgeBaseLoader(
            DATABASE_URL,
            TABLE_NAME,
            embedding_model=EMBEDDING_MODEL,
            expected_embedding_dim=2,
        ) as loader,
        pytest.raises(OSError, match="database unavailable"),
    ):
        loader.insert_batch([_record()], [[0.1, 0.2]])

    connection.rollback.assert_called_once_with()
    connection.commit.assert_not_called()
    connection.close.assert_called_once_with()
