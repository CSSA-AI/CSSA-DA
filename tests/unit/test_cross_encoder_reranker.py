import unittest
from unittest.mock import patch, MagicMock

from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.reranker.cross_encoder import CrossEncoderReranker


class TestCrossEncoderRerankerUnit(unittest.TestCase):
    def setUp(self):
        self.search_results = [
            SearchResult(
                article=Article(text="Student visa application info", questions=["student visa"]),
                score=0.1,
                rank=1,
            ),
            SearchResult(
                article=Article(text="485 visa requirements info", questions=["485 visa"]),
                score=0.2,
                rank=2,
            ),
            SearchResult(
                article=Article(text="Working holiday visa guide", questions=["working holiday"]),
                score=0.3,
                rank=3,
            ),
        ]

    @patch("app.services.rag.reranker.cross_encoder_reranker.rag_config", {
        "reranker": {
            "model_name": "fake-cross-encoder",
            "top_k": 2,
            "adapter_path": None,
        }
    })
    @patch("app.services.rag.reranker.cross_encoder_reranker.CrossEncoder")
    def test_init_uses_model_from_rag_config(self, mock_cross_encoder):
        reranker = CrossEncoderReranker()

        self.assertIsNotNone(reranker.model)
        mock_cross_encoder.assert_called_once_with("fake-cross-encoder")

    @patch("app.services.rag.reranker.cross_encoder_reranker.rag_config", {
        "reranker": {
            "model_name": "fake-cross-encoder",
            "top_k": 2,
            "adapter_path": None,
        }
    })
    @patch("app.services.rag.reranker.cross_encoder_reranker.CrossEncoder")
    def test_init_allows_manual_model_override(self, mock_cross_encoder):
        reranker = CrossEncoderReranker(model_name="manual-cross-encoder")

        mock_cross_encoder.assert_called_once_with("manual-cross-encoder")

    @patch("app.services.rag.reranker.cross_encoder_reranker.rag_config", {
        "reranker": {
            "model_name": "fake-cross-encoder",
            "top_k": 2,
            "adapter_path": "fake-adapter-path",
        }
    })
    @patch("app.services.rag.reranker.cross_encoder_reranker.PeftModel")
    @patch("app.services.rag.reranker.cross_encoder_reranker.CrossEncoder")
    def test_init_loads_adapter_when_adapter_path_exists(
        self,
        mock_cross_encoder,
        mock_peft_model,
    ):
        mock_model = MagicMock()
        mock_model.model = MagicMock()
        mock_cross_encoder.return_value = mock_model

        mock_adapter_model = MagicMock()
        mock_peft_model.from_pretrained.return_value = mock_adapter_model

        reranker = CrossEncoderReranker()

        mock_peft_model.from_pretrained.assert_called_once_with(
            mock_model.model,
            "fake-adapter-path",
        )
        self.assertEqual(reranker.model.model, mock_adapter_model)

    @patch("app.services.rag.reranker.cross_encoder_reranker.rag_config", {
        "reranker": {
            "model_name": "fake-cross-encoder",
            "top_k": 2,
            "adapter_path": None,
        }
    })
    @patch("app.services.rag.reranker.cross_encoder_reranker.CrossEncoder")
    def test_rerank_returns_empty_list_when_no_results(self, mock_cross_encoder):
        reranker = CrossEncoderReranker()

        results = reranker.rerank("student visa", [])

        self.assertEqual(results, [])

    @patch("app.services.rag.reranker.cross_encoder_reranker.rag_config", {
        "reranker": {
            "model_name": "fake-cross-encoder",
            "top_k": 2,
            "adapter_path": None,
        }
    })
    @patch("app.services.rag.reranker.cross_encoder_reranker.CrossEncoder")
    def test_rerank_scores_sorts_and_updates_rank(self, mock_cross_encoder):
        mock_model = MagicMock()
        mock_model.predict.return_value = [0.2, 0.9, 0.5]
        mock_cross_encoder.return_value = mock_model

        reranker = CrossEncoderReranker()

        results = reranker.rerank(
            query="visa requirement",
            search_results=self.search_results,
            top_k=2,
        )

        mock_model.predict.assert_called_once_with([
            ("visa requirement", "Student visa application info"),
            ("visa requirement", "485 visa requirements info"),
            ("visa requirement", "Working holiday visa guide"),
        ])

        self.assertEqual(len(results), 2)

        self.assertEqual(results[0].article.text, "485 visa requirements info")
        self.assertEqual(results[0].score, 0.9)
        self.assertEqual(results[0].rank, 1)

        self.assertEqual(results[1].article.text, "Working holiday visa guide")
        self.assertEqual(results[1].score, 0.5)
        self.assertEqual(results[1].rank, 2)

    @patch("app.services.rag.reranker.cross_encoder_reranker.rag_config", {
        "reranker": {
            "model_name": "fake-cross-encoder",
            "top_k": 2,
            "adapter_path": None,
        }
    })
    @patch("app.services.rag.reranker.cross_encoder_reranker.CrossEncoder")
    def test_rerank_uses_default_top_k_from_rag_config(self, mock_cross_encoder):
        mock_model = MagicMock()
        mock_model.predict.return_value = [0.2, 0.9, 0.5]
        mock_cross_encoder.return_value = mock_model

        reranker = CrossEncoderReranker()

        results = reranker.rerank(
            query="visa requirement",
            search_results=self.search_results,
        )

        self.assertEqual(len(results), 2)

    @patch("app.services.rag.reranker.cross_encoder_reranker.rag_config", {
        "reranker": {
            "model_name": "fake-cross-encoder",
            "top_k": 3,
            "adapter_path": None,
        }
    })
    @patch("app.services.rag.reranker.cross_encoder_reranker.CrossEncoder")
    def test_rerank_does_not_mutate_original_results(self, mock_cross_encoder):
        mock_model = MagicMock()
        mock_model.predict.return_value = [0.2, 0.9, 0.5]
        mock_cross_encoder.return_value = mock_model

        original_scores = [result.score for result in self.search_results]
        original_ranks = [result.rank for result in self.search_results]

        reranker = CrossEncoderReranker()
        reranker.rerank(
            query="visa requirement",
            search_results=self.search_results,
        )

        self.assertEqual(
            [result.score for result in self.search_results],
            original_scores,
        )
        self.assertEqual(
            [result.rank for result in self.search_results],
            original_ranks,
        )


if __name__ == "__main__":
    unittest.main()