import unittest
from typing import List, Dict, Any

from langchain_core.runnables import RunnableLambda

from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.orchestrator import LCRAGOrchestrator


# -------------------------
# Dummy retriever (Runnable)
# -------------------------
class DummyRetriever:
    def search(self, query: str) -> List[SearchResult]:
        articles = [
            Article(text="Content 1", questions=["Q1"]),
            Article(text="Content 2", questions=["Q2"]),
            Article(text="Content 3", questions=["Q3"]),
        ]
        return [
            SearchResult(article=articles[0], score=0.9, rank=1),
            SearchResult(article=articles[1], score=0.8, rank=2),
            SearchResult(article=articles[2], score=0.7, rank=3),
        ]


# -------------------------
# Dummy reranker (Runnable)
# -------------------------
class DummyReranker:
    def as_runnable(self):
        return RunnableLambda(self._run)

    def _run(self, inputs: Dict[str, Any]) -> List[SearchResult]:
        # inputs = {"query": "...", "search_results": [...]}
        return inputs["search_results"][:2]  # keep top 2


# -------------------------
# Dummy generator (Runnable)
# -------------------------
class DummyGenerator:
    def as_runnable(self):
        return RunnableLambda(self._run)

    def _run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        # inputs = {"query": "...", "reranked_results": [...]}
        articles = inputs["reranked_results"]
        contents = [a.article.text for a in articles]
        answer = f"Generated answer using: {' + '.join(contents)}"
        return {
            "answer": answer,
            "reranked_results": articles
        }


# -------------------------
# Test LCEL Orchestrator
# -------------------------
class TestLCRAGOrchestrator(unittest.TestCase):

    def setUp(self):
        self.retriever = DummyRetriever()
        self.reranker = DummyReranker()
        self.generator = DummyGenerator()

        self.orchestrator = LCRAGOrchestrator(
            retriever=self.retriever,
            reranker=self.reranker,
            generator=self.generator
        )

    def test_pipeline_runs(self):
        result = self.orchestrator.run("What is LangChain?")

        self.assertIsInstance(result, dict)
        self.assertIn("answer", result)
        self.assertIn("reranked_results", result)

        self.assertIn("Content 1", result["answer"])
        self.assertIn("Content 2", result["answer"])
        self.assertEqual(len(result["reranked_results"]), 2)

    def test_empty_query(self):
        result = self.orchestrator.run("")
        self.assertIsInstance(result, dict)
        self.assertIn("answer", result)

    def test_reranked_length(self):
        result = self.orchestrator.run("test")
        self.assertEqual(len(result["reranked_results"]), 2)


if __name__ == "__main__":
    unittest.main()
