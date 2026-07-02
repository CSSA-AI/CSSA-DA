from unittest.mock import patch

import pytest

from pipelines.loaders.postgres_knowledge_base import insert_records


DATABASE_URL = "postgresql://test:test@localhost:5432/testdb"
TABLE_NAME = "knowledge_base"


@patch("pipelines.loaders.postgres_knowledge_base.psycopg2.connect")
def test_empty_batch_returns_zero_without_connecting(mock_connect):
    inserted = insert_records([], [], DATABASE_URL, TABLE_NAME)

    assert inserted == 0
    mock_connect.assert_not_called()


@patch("pipelines.loaders.postgres_knowledge_base.psycopg2.connect")
def test_rejects_mismatched_record_and_embedding_counts(mock_connect):
    with pytest.raises(ValueError, match="same number of items"):
        insert_records([{}], [], DATABASE_URL, TABLE_NAME)

    mock_connect.assert_not_called()


@patch("pipelines.loaders.postgres_knowledge_base.psycopg2.connect")
def test_rejects_empty_embedding(mock_connect):
    with pytest.raises(ValueError, match="embedding 1 is empty"):
        insert_records([{}], [[]], DATABASE_URL, TABLE_NAME)

    mock_connect.assert_not_called()


@patch("pipelines.loaders.postgres_knowledge_base.psycopg2.connect")
def test_rejects_inconsistent_embedding_dimensions(mock_connect):
    with pytest.raises(ValueError, match="same dimension"):
        insert_records(
            [{}, {}],
            [[0.1, 0.2], [0.1]],
            DATABASE_URL,
            TABLE_NAME,
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
            expected_embedding_dim=384,
        )

    mock_connect.assert_not_called()
