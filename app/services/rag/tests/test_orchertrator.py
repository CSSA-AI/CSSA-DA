import unittest
from typing import List
from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.retriever.base import BaseRetriever
from app.services.rag.reranker.base import BaseReranker
from app.services.rag.generator.base import BaseGenerator
from app.services.rag.orchestrator import RAGOrchestrator


# Dummy Retriever: return first 3 SearchResults
class DummyRetriever(BaseRetriever):
    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        return [
            SearchResult(article=Article(title="Title 1", raw_text="Content 1"), score=0.9, rank=1),
            SearchResult(article=Article(title="Title 2", raw_text="Content 2"), score=0.8, rank=2),
            SearchResult(article=Article(title="Title 3", raw_text="Content 3"), score=0.7, rank=3)
        ]


# Dummy Reranker: return first 2 SearchResults
class DummyReranker(BaseReranker):
    def rerank(self, query: str, articles: List[SearchResult], top_k: int = 2) -> List[SearchResult]:
        return articles[:2]


# Dummy Generator: return string
class DummyGenerator(BaseGenerator):
    def generate(self, query: str, articles: List[Article]) -> str:
        contents = [article.raw_text for article in articles]
        return f"Generated answer for '{query}' using: {' + '.join(contents)}"


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
        result = self.orchestrator.run(query)

        self.assertIsInstance(result, str)
        self.assertIn("Generated answer", result)
        self.assertIn("Content 1", result)
        self.assertIn("Content 2", result)

    def test_empty_query(self):
        result = self.orchestrator.run("")
        self.assertTrue(len(result) > 0)

    def test_article_pipeline_length(self):
        retrieve_result = self.retriever.search("test")
        self.assertEqual(len(retrieve_result), 3)

        reranked = self.reranker.rerank("test", retrieve_result)
        self.assertEqual(len(reranked), 2)

        # Manually extract articles to simulate what orchestrator does
        generated = self.generator.generate("test", reranked)
        self.assertTrue("Content 1" in generated)


if __name__ == "__main__":
    unittest.main()