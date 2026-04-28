import unittest

from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.generator.context_formatter import (
    format_context_from_search_results,
)


class TestContextFormatter(unittest.TestCase):

    def _make_result(self, text="test content", question="test q", score=0.1, rank=1):
        article = Article(
            text=text,
            questions=[question] if question else [],
            source="test-source",
            author=None,
            post_date=None,
            language="en",
            created_at=None,
            tags=[],
            link="https://example.com",
        )
        return SearchResult(article=article, score=score, rank=rank)

    def test_empty_input(self):
        result = format_context_from_search_results([])
        self.assertEqual(result, "")

    def test_basic_format(self):
        sr = self._make_result()
        result = format_context_from_search_results([sr])

        self.assertIn("[资料 1]", result)
        self.assertIn("Q: test q", result)
        self.assertIn("A: test content", result)
        self.assertIn("来源: test-source", result)
        self.assertIn("链接: https://example.com", result)
        self.assertIn("检索分数: 0.1", result)
        self.assertIn("检索排名: 1", result)

    def test_max_items_limit(self):
        srs = [self._make_result(rank=i) for i in range(1, 6)]
        result = format_context_from_search_results(srs, max_items=2)

        self.assertIn("[资料 1]", result)
        self.assertIn("[资料 2]", result)
        self.assertNotIn("[资料 3]", result)

    def test_truncate(self):
        long_text = "a" * 50
        sr = self._make_result(text=long_text)

        result = format_context_from_search_results(
            [sr],
            max_chars_per_item=10,
        )

        self.assertIn("aaaaaaaaaa...", result)

    def test_missing_question(self):
        sr = self._make_result(question=None)
        result = format_context_from_search_results([sr])

        self.assertIn("Q:", result)  # 空但不报错

    def test_none_fields_handled(self):
        article = Article(
            text="text",
            questions=[],
            source=None,
            author=None,
            post_date=None,
            language=None,
            created_at=None,
            tags=[],
            link=None,
        )
        sr = SearchResult(article=article, score=0.2, rank=1)

        result = format_context_from_search_results([sr])

        self.assertIn("来源:", result)
        self.assertIn("链接:", result)


if __name__ == "__main__":
    unittest.main()