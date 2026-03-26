import unittest
from app.services.rag.retriever.faiss_retriever import FAISSRetriever
from app.schemas.article import Article
from app.schemas.search_result import SearchResult


class TestFAISSRetriever(unittest.TestCase):
    def setUp(self):
        # Create 3 mock articles
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

        # LangChain retriever
        self.retriever = FAISSRetriever(
            input_list=self.articles,
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )

    def test_search_returns_results(self):
        results = self.retriever.search("How to get a student visa", top_k=2)

        # Basic checks
        self.assertIsInstance(results, list)
        self.assertGreaterEqual(len(results), 1)

        for item in results:
            self.assertIsInstance(item, SearchResult)
            self.assertIsInstance(item.article, Article)
            self.assertIsInstance(item.score, float)
            self.assertIsInstance(item.rank, int)

    def test_search_top1_is_relevant(self):
        results = self.retriever.search("student visa", top_k=1)
        top_result = results[0]
        top_article = top_result.article

        # Check relevance in question or text
        content = (
            top_article.questions[0].lower()
            if top_article.questions else top_article.text.lower()
        )
        self.assertIn("student", content)


if __name__ == "__main__":
    unittest.main()
