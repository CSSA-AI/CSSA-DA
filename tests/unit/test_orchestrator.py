import unittest
from typing import List

from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.retriever.base import BaseRetriever
from app.services.rag.reranker.base import BaseReranker
from app.services.rag.generator.base import BaseGenerator
from app.services.rag.orchestrator import RAGOrchestrator


class DummyRetriever(BaseRetriever):
    def __init__(self):
        pass

    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        return [
            SearchResult(
                article=Article(text="Content 1", questions=["Q1"]),
                score=0.9,
                rank=1
            ),
            SearchResult(
                article=Article(text="Content 2", questions=["Q2"]),
                score=0.8,
                rank=2
            ),
            SearchResult(
                article=Article(text="Content 3", questions=["Q3"]),
                score=0.7,
                rank=3
            )
        ]


class DummyReranker(BaseReranker):
    def __init__(self):
        pass

    def rerank(self, query: str, search_results: List[SearchResult], top_k: int = 2) -> List[SearchResult]:
        return search_results[:2]


class DummyGenerator(BaseGenerator):
    def __init__(self):
        pass

    def generate(self, query: str, articles: List[Article]) -> str:
        contents = [article.text for article in articles]
        return f"Generated answer for '{query}' using: {' + '.join(contents)}"

    def generate_text(self, query: str, search_results: List[SearchResult], session_id: str = "default") -> str:
        articles = [item.article for item in search_results]
        return self.generate(query, articles)


class TestRAGOrchestrator(unittest.TestCase):
    def setUp(self):
        self.retriever = DummyRetriever()
        self.reranker = DummyReranker()
        self.generator = DummyGenerator()
        self.orchestrator = RAGOrchestrator(
            retriever=self.retriever,
            reranker=self.reranker,
            generator=self.generator
        )

    def test_orchestrator_pipeline(self):
        query = "What is LangChain?"
        answer, sources = self.orchestrator.run(query)

        self.assertIsInstance(answer, str)
        self.assertIsInstance(sources, list)
        self.assertEqual(len(sources), 2)
        self.assertIn("Generated answer", answer)
        self.assertIn("Content 1", answer)
        self.assertIn("Content 2", answer)

    def test_empty_query(self):
        answer, sources = self.orchestrator.run("")

        self.assertIsInstance(answer, str)
        self.assertTrue(len(answer) > 0)
        self.assertEqual(len(sources), 2)

    def test_article_pipeline_length(self):
        retrieve_result = self.retriever.search("test")
        self.assertEqual(len(retrieve_result), 3)

        reranked = self.reranker.rerank("test", retrieve_result)
        self.assertEqual(len(reranked), 2)

        generated = self.generator.generate_text("test", reranked, session_id="default")
        self.assertIn("Content 1", generated)
        self.assertIn("Content 2", generated)


if __name__ == "__main__":
    unittest.main()