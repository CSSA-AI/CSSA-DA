import unittest
from unittest.mock import patch, MagicMock
import numpy as np
import torch

from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.retriever.faiss_retriever import FAISSRetriever


class TestFAISSRetrieverUnit(unittest.TestCase):
    def setUp(self):
        self.articles = [
            Article(
                text="Info about applying for a student visa",
                questions=["How to apply for a student visa"]
            ),
            Article(
                text="Details on postgraduate 485 visa requirements",
                questions=["Postgraduate 485 visa requirements"]
            ),
            Article(
                text="Guide for working holiday visa",
                questions=["Working holiday visa guide"]
            )
        ]

    @patch("app.services.rag.retriever.faiss_retriever.SentenceTransformer")
    def test_init_success(self, mock_st):
        retriever = FAISSRetriever(
            input_list=self.articles,
            model_name="fake-model"
        )

        self.assertEqual(retriever.articles, self.articles)
        self.assertEqual(retriever.model_name, "fake-model")
        self.assertIsNotNone(retriever.model)
        self.assertFalse(retriever._is_built)
        self.assertEqual(len(retriever.id_mapping), 3)
        mock_st.assert_called_once_with("fake-model")

    @patch("app.services.rag.retriever.faiss_retriever.rag_config", {
        "retriever": {
            "embedding_model": "default-embedding-model",
            "top_k": 5
        },
        "faiss": {
            "index_path": "data/faiss/index.faiss",
            "embedding_path": "data/faiss/question_embeddings.pt",
            "idmap_path": "data/faiss/id_mapping.json"
        }
    })
    @patch("app.services.rag.retriever.faiss_retriever.SentenceTransformer")
    def test_init_uses_default_model_from_rag_config(self, mock_st):
        retriever = FAISSRetriever(input_list=self.articles)

        self.assertEqual(retriever.model_name, "default-embedding-model")
        mock_st.assert_called_once_with("default-embedding-model")

    def test_init_raises_type_error_when_input_not_article_list(self):
        with self.assertRaises(TypeError):
            FAISSRetriever(
                input_list=["not an article"],
                model_name="fake-model"
            )

    @patch("app.services.rag.retriever.faiss_retriever.SentenceTransformer")
    def test_encode_articles_uses_first_question(self, mock_st):
        mock_model = MagicMock()
        mock_model.encode.return_value = torch.tensor([
            [1.0, 0.0],
            [0.0, 1.0],
            [0.5, 0.5]
        ])
        mock_st.return_value = mock_model

        retriever = FAISSRetriever(
            input_list=self.articles,
            model_name="fake-model"
        )

        embeddings = retriever._encode_articles()

        mock_model.encode.assert_called_once_with(
            [
                "How to apply for a student visa",
                "Postgraduate 485 visa requirements",
                "Working holiday visa guide"
            ],
            convert_to_tensor=True,
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=True
        )

        self.assertTrue(torch.equal(embeddings, retriever.question_embeddings))

    @patch("app.services.rag.retriever.faiss_retriever.SentenceTransformer")
    def test_encode_articles_raises_when_article_has_no_questions(self, mock_st):
        bad_articles = [
            Article(text="No question article", questions=[])
        ]

        retriever = FAISSRetriever(
            input_list=bad_articles,
            model_name="fake-model"
        )

        with self.assertRaises(ValueError):
            retriever._encode_articles()

    @patch("app.services.rag.retriever.faiss_retriever.SentenceTransformer")
    def test_build_index_raises_if_embeddings_not_ready(self, mock_st):
        retriever = FAISSRetriever(
            input_list=self.articles,
            model_name="fake-model"
        )

        with self.assertRaises(RuntimeError):
            retriever._build_index()

    @patch("app.services.rag.retriever.faiss_retriever.SentenceTransformer")
    def test_build_index_success(self, mock_st):
        retriever = FAISSRetriever(
            input_list=self.articles,
            model_name="fake-model"
        )

        retriever.question_embeddings = torch.tensor([
            [1.0, 0.0],
            [0.0, 1.0],
            [0.5, 0.5]
        ])

        retriever._build_index()

        self.assertIsNotNone(retriever.index)
        self.assertTrue(retriever._is_built)
        self.assertEqual(retriever.index.ntotal, 3)

    @patch("app.services.rag.retriever.faiss_retriever.SentenceTransformer")
    def test_encode_query_returns_numpy_float32(self, mock_st):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.2, 0.8]], dtype=np.float32)
        mock_st.return_value = mock_model

        retriever = FAISSRetriever(
            input_list=self.articles,
            model_name="fake-model"
        )

        vec = retriever._encode_query("student visa")

        mock_model.encode.assert_called_once_with(
            ["student visa"],
            normalize_embeddings=True,
            convert_to_numpy=True
        )
        self.assertIsInstance(vec, np.ndarray)
        self.assertEqual(vec.dtype, np.float32)
        self.assertEqual(vec.shape, (1, 2))

    @patch("app.services.rag.retriever.faiss_retriever.SentenceTransformer")
    def test_search_returns_search_results(self, mock_st):
        mock_model = MagicMock()

        def fake_encode(inputs, **kwargs):
            if kwargs.get("convert_to_tensor", False):
                return torch.tensor([
                    [1.0, 0.0],
                    [0.0, 1.0],
                    [0.8, 0.2]
                ])
            if kwargs.get("convert_to_numpy", False):
                return np.array([[1.0, 0.0]], dtype=np.float32)
            raise ValueError("Unexpected encode call")

        mock_model.encode.side_effect = fake_encode
        mock_st.return_value = mock_model

        retriever = FAISSRetriever(
            input_list=self.articles,
            model_name="fake-model"
        )

        results = retriever.search("student visa", top_k=2)

        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 2)

        for item in results:
            self.assertIsInstance(item, SearchResult)
            self.assertIsInstance(item.article, Article)
            self.assertIsInstance(item.score, float)
            self.assertIsInstance(item.rank, int)

    @patch("app.services.rag.retriever.faiss_retriever.rag_config", {
        "retriever": {
            "embedding_model": "fake-model",
            "top_k": 2
        },
        "faiss": {
            "index_path": "data/faiss/index.faiss",
            "embedding_path": "data/faiss/question_embeddings.pt",
            "idmap_path": "data/faiss/id_mapping.json"
        }
    })
    @patch("app.services.rag.retriever.faiss_retriever.SentenceTransformer")
    def test_search_uses_default_top_k_from_rag_config(self, mock_st):
        mock_model = MagicMock()

        def fake_encode(inputs, **kwargs):
            if kwargs.get("convert_to_tensor", False):
                return torch.tensor([
                    [1.0, 0.0],
                    [0.0, 1.0],
                    [0.8, 0.2]
                ])
            if kwargs.get("convert_to_numpy", False):
                return np.array([[1.0, 0.0]], dtype=np.float32)
            raise ValueError("Unexpected encode call")

        mock_model.encode.side_effect = fake_encode
        mock_st.return_value = mock_model

        retriever = FAISSRetriever(input_list=self.articles)

        results = retriever.search("student visa")

        self.assertEqual(len(results), 2)

    @patch("app.services.rag.retriever.faiss_retriever.SentenceTransformer")
    def test_search_builds_index_only_once(self, mock_st):
        mock_model = MagicMock()

        def fake_encode(inputs, **kwargs):
            if kwargs.get("convert_to_tensor", False):
                return torch.tensor([
                    [1.0, 0.0],
                    [0.0, 1.0],
                    [0.8, 0.2]
                ])
            if kwargs.get("convert_to_numpy", False):
                return np.array([[1.0, 0.0]], dtype=np.float32)
            raise ValueError("Unexpected encode call")

        mock_model.encode.side_effect = fake_encode
        mock_st.return_value = mock_model

        retriever = FAISSRetriever(
            input_list=self.articles,
            model_name="fake-model"
        )

        with patch.object(
            retriever,
            "_encode_articles",
            wraps=retriever._encode_articles
        ) as mock_encode_articles, patch.object(
            retriever,
            "_build_index",
            wraps=retriever._build_index
        ) as mock_build_index:

            retriever.search("student visa", top_k=2)
            retriever.search("485 visa", top_k=2)

            self.assertEqual(mock_encode_articles.call_count, 1)
            self.assertEqual(mock_build_index.call_count, 1)

    @patch("app.services.rag.retriever.faiss_retriever.SentenceTransformer")
    def test_search_top_result_is_expected_with_mocked_embeddings(self, mock_st):
        mock_model = MagicMock()

        def fake_encode(inputs, **kwargs):
            if kwargs.get("convert_to_tensor", False):
                return torch.tensor([
                    [1.0, 0.0],
                    [0.0, 1.0],
                    [0.3, 0.7]
                ])
            if kwargs.get("convert_to_numpy", False):
                return np.array([[1.0, 0.0]], dtype=np.float32)
            raise ValueError("Unexpected encode call")

        mock_model.encode.side_effect = fake_encode
        mock_st.return_value = mock_model

        retriever = FAISSRetriever(
            input_list=self.articles,
            model_name="fake-model"
        )

        results = retriever.search("student visa", top_k=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].article.questions[0],
            "How to apply for a student visa"
        )
        self.assertEqual(results[0].rank, 1)


if __name__ == "__main__":
    unittest.main()