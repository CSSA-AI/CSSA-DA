import unittest
from packages.rag_core.retriever.retriever import Retriever
from packages.rag_core.utils.article import Article
import torch
import os

class TestRetriever(unittest.TestCase):

    def setUp(self):
        """Set up test articles and retriever"""
        self.articles = [
            Article(title="AI and Climate", raw_text="Detailed discussion."),
            Article(title="Machine Learning", raw_text="Details about ML."),
            Article(title="Deep Learning", raw_text="More about deep learning.")
        ]
        self.model_name = "sentence-transformers/all-MiniLM-L6-v2"
        self.retriever = Retriever(input_list=self.articles, model_name=self.model_name)

    def test_vectorize_sentence_transformer(self):
        """Test vectorization produces correct shape and type"""
        embeddings = self.retriever.vectorize_sentence_transformer()
        self.assertEqual(len(embeddings), len(self.articles))
        self.assertEqual(embeddings.shape[1], 384)  # for MiniLM-L6-v2
        self.assertTrue(torch.is_tensor(embeddings))

    def test_id_mapping(self):
        """Test ID mapping contains correct keys"""
        mapping = self.retriever.get_id_mapping()
        self.assertEqual(len(mapping), len(self.articles))
        self.assertIsInstance(mapping["0"], Article)

    def test_build_faiss_index(self):
        """Test FAISS index is built and not None"""
        self.retriever.vectorize_sentence_transformer()
        index = self.retriever.build_faiss_index()
        self.assertIsNotNone(index)
        self.assertTrue(index.is_trained)
        self.assertEqual(index.ntotal, len(self.articles))

    def test_search(self):
        """Test that search returns relevant results"""
        self.retriever.vectorize_sentence_transformer()
        self.retriever.get_id_mapping()
        self.retriever.build_faiss_index()

        results = self.retriever.search("climate")
        self.assertGreaterEqual(len(results), 1)
        self.assertIsInstance(results[0][2], Article)

    def tearDown(self):
        """Clean up if any files were written (optional)"""
        pass

if __name__ == '__main__':
    unittest.main()
