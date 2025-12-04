import unittest
from typing import List, Tuple
from packages.rag_core.utils.article import Article
from packages.rag_core.retriever.base import BaseRetriever
from packages.rag_core.reranker.base import BaseReranker
from packages.rag_core.generator.base import BaseGenerator
from apps.api.src.orchestrator.rag_orchestrator import RAGOrchestrator


# Dummy Retriever: return first 3 articles
class DummyRetriever(BaseRetriever):
    def search(self, query: str, top_k: int = 5) -> List[Tuple[int, float, Article]]:
        return [
            (0, 0.9, Article(title="Title 1", raw_text="Content 1")),
            (1, 0.8, Article(title="Title 2", raw_text="Content 2")),
            (2, 0.7, Article(title="Title 3", raw_text="Content 3"))
        ]


# Dummy Reranker: return first 2 articles
class DummyReranker(BaseReranker):
    def rerank(self, query: str, articles: List[Tuple[int, float, Article]], top_k: int = 2) -> List[Article]:
        return [articles[0][2], articles[1][2]]


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

        generated = self.generator.generate("test", reranked)
        self.assertTrue("Content 1" in generated)


if __name__ == "__main__":
    unittest.main()

