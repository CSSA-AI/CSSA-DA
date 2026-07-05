import unittest
from unittest.mock import patch, MagicMock
import numpy as np

from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.retriever.pg_retriever import PGVectorRetriever


class TestPGVectorRetrieverUnit(unittest.TestCase):

    @patch("app.services.rag.retriever.pg_retriever.SentenceTransformer")
    @patch("app.services.rag.retriever.pg_retriever.psycopg2.connect")
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
    def test_init_success(self, mock_connect, mock_st):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        retriever = PGVectorRetriever(
            database_url="postgresql://test:test@localhost:5432/testdb"
        )

        self.assertEqual(retriever.model_name, "fake-embedding-model")
        self.assertEqual(retriever.model_revision, "revision-123")
        self.assertEqual(retriever.table_name, "knowledge_base")
        self.assertEqual(retriever.conn, mock_conn)

        mock_connect.assert_called_once_with(
            "postgresql://test:test@localhost:5432/testdb"
        )
        mock_st.assert_called_once_with(
            "fake-embedding-model",
            revision="revision-123",
        )

    @patch("app.services.rag.retriever.pg_retriever.SentenceTransformer")
    @patch("app.services.rag.retriever.pg_retriever.psycopg2.connect")
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
    def test_init_allows_manual_override(self, mock_connect, mock_st):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

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
    @patch("app.services.rag.retriever.pg_retriever.psycopg2.connect")
    @patch("app.services.rag.retriever.pg_retriever.rag_config", {
        "retriever": {
            "embedding_model": "fake-embedding-model",
            "top_k": 5,
        },
        "pgvector": {
            "table_name": "knowledge_base",
        },
    })
    def test_encode_query(self, mock_connect, mock_st):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]])
        mock_st.return_value = mock_model
        mock_connect.return_value = MagicMock()

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
    @patch("app.services.rag.retriever.pg_retriever.psycopg2.connect")
    @patch("app.services.rag.retriever.pg_retriever.rag_config", {
        "retriever": {
            "embedding_model": "fake-embedding-model",
            "top_k": 2,
        },
        "pgvector": {
            "table_name": "knowledge_base",
        },
    })
    def test_search_returns_search_results(self, mock_connect, mock_st):
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
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_connect.return_value = mock_conn

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
        self.assertEqual(params[1], [0.1, 0.2, 0.3])
        self.assertEqual(params[2], 2)

    @patch("app.services.rag.retriever.pg_retriever.SentenceTransformer")
    @patch("app.services.rag.retriever.pg_retriever.psycopg2.connect")
    @patch("app.services.rag.retriever.pg_retriever.rag_config", {
        "retriever": {
            "embedding_model": "fake-embedding-model",
            "top_k": 5,
        },
        "pgvector": {
            "table_name": "knowledge_base",
        },
    })
    def test_search_manual_top_k_overrides_config(self, mock_connect, mock_st):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]])
        mock_st.return_value = mock_model

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        retriever = PGVectorRetriever(
            database_url="postgresql://test:test@localhost:5432/testdb"
        )

        results = retriever.search("student visa", top_k=3)

        self.assertEqual(results, [])

        mock_cursor.execute.assert_called_once()
        _, params = mock_cursor.execute.call_args[0]
        self.assertEqual(params[2], 3)

    @patch("app.services.rag.retriever.pg_retriever.SentenceTransformer")
    @patch("app.services.rag.retriever.pg_retriever.psycopg2.connect")
    @patch("app.services.rag.retriever.pg_retriever.rag_config", {
        "retriever": {
            "embedding_model": "fake-embedding-model",
            "top_k": 5,
        },
        "pgvector": {
            "table_name": "knowledge_base",
        },
    })
    def test_close_closes_connection(self, mock_connect, mock_st):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        retriever = PGVectorRetriever(
            database_url="postgresql://test:test@localhost:5432/testdb"
        )

        retriever.close()

        mock_conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
