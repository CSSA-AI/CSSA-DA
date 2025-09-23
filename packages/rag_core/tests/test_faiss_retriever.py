import unittest
from packages.rag_core.retriever.faiss_retriever import FAISSRetriever
from packages.rag_core.utils.article import Article

class TestFAISSRetriever(unittest.TestCase):
    def setUp(self):
        # Create 3 mock articles
        self.articles = [
            Article(text="Info about applying for a student visa", questions=["How to apply for a student visa"]),
            Article(text="Details on postgraduate 485 visa requirements", questions=["Postgraduate 485 visa requirements"]),
            Article(text="Guide for working holiday visa", questions=["Working holiday visa guide"])
        ]

        self.retriever = FAISSRetriever(
            input_list=self.articles,
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )

    def test_search_returns_results(self):
        # Query the retriever
        results = self.retriever.search("How to get a student visa", top_k=2)

        # Check result format
        self.assertIsInstance(results, list)
        self.assertGreaterEqual(len(results), 1)

        for item in results:
            self.assertIsInstance(item, tuple)
            self.assertEqual(len(item), 3)
            index, score, article = item
            self.assertIsInstance(index, int)
            self.assertIsInstance(score, float)
            self.assertIsInstance(article, Article)

    def test_search_top1_is_relevant(self):
        results = self.retriever.search("student visa", top_k=1)
        top_article = results[0][2]
        # Check relevance in question or text
        content = top_article.questions[0].lower() if top_article.questions else top_article.text.lower()
        self.assertIn("student", content)

if __name__ == "__main__":
    unittest.main()
