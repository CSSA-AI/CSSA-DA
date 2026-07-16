import unittest
from unittest.mock import patch, MagicMock

from app.core.config import rag_config
from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.model_registry import model_registry
from app.services.rag.reranker.cross_encoder_reranker import CrossEncoderReranker


class TestCrossEncoderRerankerUnit(unittest.TestCase):
    @patch("app.services.rag.reranker.cross_encoder_reranker.rag_config", {
        "reranker": {
            "model_name": "fake-cross-encoder",
            "model_revision": "fake-revision",
            "top_k": 2,
            "adapter_path": None,
        }
    })
    def test_init_uses_shared_configured_model(self):
        reranker = CrossEncoderReranker()

        self.assertIs(reranker.model, self.shared_reranker_model)
        self.mock_get_reranker_model.assert_called_once_with()

    def test_default_config_pins_model_revision(self):
        self.assertEqual(
            rag_config["reranker"]["model_revision"],
            "7b0235231ca2674cb8ca8f022859a6eba2b1c968",
        )

    def setUp(self):
        self.shared_reranker_model = MagicMock()
        patcher = patch.object(
            model_registry,
            "get_reranker_model",
            return_value=self.shared_reranker_model,
        )
        self.mock_get_reranker_model = patcher.start()
        self.addCleanup(patcher.stop)
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
            "model_revision": "fake-revision",
            "top_k": 2,
            "adapter_path": None,
        }
    })
    @patch("app.services.rag.reranker.cross_encoder_reranker.CrossEncoder")
    def test_init_uses_model_from_rag_config(self, mock_cross_encoder):
        reranker = CrossEncoderReranker()

        self.assertIs(reranker.model, self.shared_reranker_model)
        self.mock_get_reranker_model.assert_called_once_with()
        mock_cross_encoder.assert_not_called()

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
        self.mock_get_reranker_model.assert_not_called()

    @patch("app.services.rag.reranker.cross_encoder_reranker.rag_config", {
        "reranker": {
            "model_name": "fake-cross-encoder",
            "model_revision": "fake-revision",
            "top_k": 2,
            "adapter_path": None,
        }
    })
    @patch("app.services.rag.reranker.cross_encoder_reranker.CrossEncoder")
    def test_init_allows_manual_revision_override(self, mock_cross_encoder):
        CrossEncoderReranker(model_revision="manual-revision")

        mock_cross_encoder.assert_called_once_with(
            "fake-cross-encoder",
            revision="manual-revision",
        )

    @patch("app.services.rag.reranker.cross_encoder_reranker.rag_config", {
        "reranker": {
            "model_name": "fake-cross-encoder",
            "top_k": 2,
            "adapter_path": "fake-adapter-path",
        }
    })
    def test_init_uses_shared_model_with_configured_adapter(self):
        reranker = CrossEncoderReranker()

        self.assertIs(reranker.model, self.shared_reranker_model)
        self.mock_get_reranker_model.assert_called_once_with()

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
        mock_model = self.shared_reranker_model
        mock_model.predict.return_value = [0.2, 0.9, 0.5]

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
        mock_model = self.shared_reranker_model
        mock_model.predict.return_value = [0.2, 0.9, 0.5]

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
        mock_model = self.shared_reranker_model
        mock_model.predict.return_value = [0.2, 0.9, 0.5]

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
