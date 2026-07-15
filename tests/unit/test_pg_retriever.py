import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock
import numpy as np
from psycopg2 import OperationalError
from psycopg2.pool import PoolError

from app.core.config import settings
from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.errors import RetrievalUnavailableError
from app.services.rag.retriever.pg_retriever import PGVectorRetriever


class TestPGVectorRetrieverUnit(unittest.TestCase):

    @patch("app.services.rag.retriever.pg_retriever.SentenceTransformer")
    @patch("app.services.rag.retriever.pg_retriever.ThreadedConnectionPool")
    @patch("app.services.rag.retriever.pg_retriever.rag_config", {
        "retriever": {
            "embedding_model": "fake-embedding-model",
            "embedding_revision": "revision-123",
            "top_k": 5,
        },
        "pgvector": {
            "table_name": "knowledge_base",
        },
    })
    def test_init_loads_configured_model_from_local_directory(
        self,
        mock_pool_class,
        mock_st,
    ):
        with TemporaryDirectory() as temp_dir:
            model_dir = Path(temp_dir)
            embedding_dir = model_dir / "embedding"
            embedding_dir.mkdir()

            with patch.object(settings, "MODEL_DIR", model_dir):
                retriever = PGVectorRetriever(
                    database_url="postgresql://test:test@localhost:5432/testdb"
                )

        self.assertEqual(retriever.model_name, "fake-embedding-model")
        self.assertEqual(retriever.model_revision, "revision-123")
        mock_st.assert_called_once_with(
            str(embedding_dir.resolve()),
            local_files_only=True,
        )


    @patch("app.services.rag.retriever.pg_retriever.SentenceTransformer")
    @patch("app.services.rag.retriever.pg_retriever.ThreadedConnectionPool")
    @patch("app.services.rag.retriever.pg_retriever.rag_config", {
        "retriever": {
            "embedding_model": "fake-embedding-model",
            "embedding_revision": "revision-123",
            "top_k": 5,
        },
        "pgvector": {
            "table_name": "knowledge_base",
        },
    })
    def test_init_success(self, mock_pool_class, mock_st):
        mock_conn = MagicMock()
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        retriever = PGVectorRetriever(
            database_url="postgresql://test:test@localhost:5432/testdb"
        )

        self.assertEqual(retriever.model_name, "fake-embedding-model")
        self.assertEqual(retriever.model_revision, "revision-123")
        self.assertEqual(retriever.table_name, "knowledge_base")
        self.assertEqual(retriever.pool, mock_pool)

        mock_pool_class.assert_called_once_with(
            minconn=1,
            maxconn=5,
            dsn="postgresql://test:test@localhost:5432/testdb",
        )
        mock_st.assert_called_once_with(
            "fake-embedding-model",
            revision="revision-123",
        )

    @patch("app.services.rag.retriever.pg_retriever.SentenceTransformer")
    @patch("app.services.rag.retriever.pg_retriever.ThreadedConnectionPool")
    @patch("app.services.rag.retriever.pg_retriever.rag_config", {
        "retriever": {
            "embedding_model": "yaml-model",
            "embedding_revision": "yaml-revision",
            "top_k": 5,
        },
        "pgvector": {
            "table_name": "yaml_table",
        },
    })
    def test_init_allows_manual_override(self, mock_pool_class, mock_st):

        retriever = PGVectorRetriever(
            database_url="postgresql://test:test@localhost:5432/testdb",
            model_name="manual-model",
            table_name="manual_table",
        )

        self.assertEqual(retriever.model_name, "manual-model")
        self.assertIsNone(retriever.model_revision)
        self.assertEqual(retriever.table_name, "manual_table")
        mock_st.assert_called_once_with("manual-model")

    @patch("app.services.rag.retriever.pg_retriever.settings")
    @patch("app.services.rag.retriever.pg_retriever.rag_config", {
        "retriever": {
            "embedding_model": "fake-embedding-model",
            "top_k": 5,
        },
        "pgvector": {
            "table_name": "knowledge_base",
        },
    })
    def test_init_raises_when_database_url_missing(self, mock_settings):
        mock_settings.DATABASE_URL = None

        with self.assertRaises(ValueError):
            PGVectorRetriever()

    @patch("app.services.rag.retriever.pg_retriever.SentenceTransformer")
    @patch("app.services.rag.retriever.pg_retriever.ThreadedConnectionPool")
    @patch("app.services.rag.retriever.pg_retriever.rag_config", {
        "retriever": {
            "embedding_model": "fake-embedding-model",
            "top_k": 5,
        },
        "pgvector": {
            "table_name": "knowledge_base",
        },
    })
    def test_encode_query(self, mock_pool_class, mock_st):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]])
        mock_st.return_value = mock_model
        mock_pool_class.return_value = MagicMock()

        retriever = PGVectorRetriever(
            database_url="postgresql://test:test@localhost:5432/testdb"
        )

        vec = retriever._encode_query("student visa")

        mock_model.encode.assert_called_once_with(
            ["student visa"],
            normalize_embeddings=True,
        )
        np.testing.assert_array_equal(vec, np.array([0.1, 0.2, 0.3]))

    @patch("app.services.rag.retriever.pg_retriever.SentenceTransformer")
    @patch("app.services.rag.retriever.pg_retriever.ThreadedConnectionPool")
    @patch("app.services.rag.retriever.pg_retriever.rag_config", {
        "retriever": {
            "embedding_model": "fake-embedding-model",
            "embedding_revision": "revision-123",
            "top_k": 2,
        },
        "pgvector": {
            "table_name": "knowledge_base",
        },
    })
    def test_search_returns_search_results(self, mock_pool_class, mock_st):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]])
        mock_st.return_value = mock_model

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "question_text": "How to apply for a student visa?",
                "content": "Student visa application information.",
                "source": "test-source",
                "author": "test-author",
                "post_date": None,
                "language": "en",
                "created_at": None,
                "tags": ["visa", "student"],
                "link": "https://example.com/student-visa",
                "distance": 0.12,
            },
            {
                "question_text": "What are 485 visa requirements?",
                "content": "485 visa requirement details.",
                "source": "test-source",
                "author": None,
                "post_date": None,
                "language": "en",
                "created_at": None,
                "tags": None,
                "link": None,
                "distance": 0.25,
            },
        ]

        mock_conn = MagicMock()
        mock_conn.closed = 0
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_pool_class.return_value = mock_pool

        retriever = PGVectorRetriever(
            database_url="postgresql://test:test@localhost:5432/testdb"
        )

        results = retriever.search("student visa")

        self.assertEqual(len(results), 2)

        for result in results:
            self.assertIsInstance(result, SearchResult)
            self.assertIsInstance(result.article, Article)
            self.assertIsInstance(result.score, float)
            self.assertIsInstance(result.rank, int)

        self.assertEqual(results[0].article.text, "Student visa application information.")
        self.assertEqual(results[0].article.questions, ["How to apply for a student visa?"])
        self.assertEqual(results[0].score, -0.12)
        self.assertEqual(results[0].rank, 1)

        self.assertEqual(results[1].article.tags, [])
        self.assertEqual(results[1].score, -0.25)
        self.assertEqual(results[1].rank, 2)

        mock_cursor.execute.assert_called_once()
        _, params = mock_cursor.execute.call_args[0]
        self.assertEqual(
            params,
            (
                [0.1, 0.2, 0.3],
                "fake-embedding-model",
                "revision-123",
                [0.1, 0.2, 0.3],
                2,
            ),
        )
        mock_conn.rollback.assert_called_once_with()
        mock_pool.putconn.assert_called_once_with(mock_conn, close=False)

    @patch("app.services.rag.retriever.pg_retriever.SentenceTransformer")
    @patch("app.services.rag.retriever.pg_retriever.ThreadedConnectionPool")
    @patch("app.services.rag.retriever.pg_retriever.rag_config", {
        "retriever": {
            "embedding_model": "fake-embedding-model",
            "top_k": 5,
        },
        "pgvector": {
            "table_name": "knowledge_base",
        },
    })
    def test_search_manual_top_k_overrides_config(self, mock_pool_class, mock_st):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]])
        mock_st.return_value = mock_model

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.closed = 0
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_pool_class.return_value = mock_pool

        retriever = PGVectorRetriever(
            database_url="postgresql://test:test@localhost:5432/testdb"
        )

        results = retriever.search("student visa", top_k=3)

        self.assertEqual(results, [])

        mock_cursor.execute.assert_called_once()
        _, params = mock_cursor.execute.call_args[0]
        self.assertEqual(params[4], 3)

    @patch("app.services.rag.retriever.pg_retriever.SentenceTransformer")
    @patch("app.services.rag.retriever.pg_retriever.ThreadedConnectionPool")
    @patch("app.services.rag.retriever.pg_retriever.rag_config", {
        "retriever": {
            "embedding_model": "fake-embedding-model",
            "top_k": 5,
        },
        "pgvector": {
            "table_name": "knowledge_base",
        },
    })
    def test_search_discards_connection_when_rollback_fails(
        self,
        mock_pool_class,
        mock_st,
    ):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]])
        mock_st.return_value = mock_model

        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = RuntimeError("query failed")
        mock_conn = MagicMock()
        mock_conn.closed = 0
        mock_conn.rollback.side_effect = RuntimeError("connection lost")
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_pool_class.return_value = mock_pool

        retriever = PGVectorRetriever(
            database_url="postgresql://test:test@localhost:5432/testdb"
        )

        with self.assertRaisesRegex(RuntimeError, "query failed"):
            retriever.search("student visa")

        mock_pool.putconn.assert_called_once_with(mock_conn, close=True)

    @patch("app.services.rag.retriever.pg_retriever.SentenceTransformer")
    @patch("app.services.rag.retriever.pg_retriever.ThreadedConnectionPool")
    @patch("app.services.rag.retriever.pg_retriever.rag_config", {
        "retriever": {
            "embedding_model": "fake-embedding-model",
            "top_k": 5,
        },
        "pgvector": {
            "table_name": "knowledge_base",
        },
    })
    def test_search_translates_connection_pool_failure(
        self,
        mock_pool_class,
        mock_st,
    ):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]])
        mock_st.return_value = mock_model
        mock_pool = MagicMock()
        mock_pool.getconn.side_effect = PoolError("pool exhausted")
        mock_pool_class.return_value = mock_pool
        retriever = PGVectorRetriever(
            database_url="postgresql://test:test@localhost:5432/testdb"
        )

        with self.assertRaises(RetrievalUnavailableError):
            retriever.search("student visa")

    @patch("app.services.rag.retriever.pg_retriever.SentenceTransformer")
    @patch("app.services.rag.retriever.pg_retriever.ThreadedConnectionPool")
    @patch("app.services.rag.retriever.pg_retriever.rag_config", {
        "retriever": {
            "embedding_model": "fake-embedding-model",
            "top_k": 5,
        },
        "pgvector": {
            "table_name": "knowledge_base",
        },
    })
    def test_search_translates_database_query_failure(
        self,
        mock_pool_class,
        mock_st,
    ):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]])
        mock_st.return_value = mock_model
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = OperationalError("database lost")
        mock_conn = MagicMock()
        mock_conn.closed = 0
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mock_pool_class.return_value = mock_pool
        retriever = PGVectorRetriever(
            database_url="postgresql://test:test@localhost:5432/testdb"
        )

        with self.assertRaises(RetrievalUnavailableError):
            retriever.search("student visa")

        mock_conn.rollback.assert_called_once_with()
        mock_pool.putconn.assert_called_once_with(mock_conn, close=False)

    @patch("app.services.rag.retriever.pg_retriever.SentenceTransformer")
    @patch("app.services.rag.retriever.pg_retriever.ThreadedConnectionPool")
    @patch("app.services.rag.retriever.pg_retriever.rag_config", {
        "retriever": {
            "embedding_model": "fake-embedding-model",
            "top_k": 5,
        },
        "pgvector": {
            "table_name": "knowledge_base",
        },
    })
    def test_close_closes_pool(self, mock_pool_class, mock_st):
        mock_pool = MagicMock()
        mock_pool_class.return_value = mock_pool

        retriever = PGVectorRetriever(
            database_url="postgresql://test:test@localhost:5432/testdb"
        )

        retriever.close()

        mock_pool.closeall.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
