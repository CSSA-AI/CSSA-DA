# app/services/rag/generator/context_formatter.py

from __future__ import annotations

from typing import Any, List

from app.schemas.search_result import SearchResult


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _truncate(text: str, max_chars: int | None) -> str:
    if not max_chars or max_chars <= 0:
        return text

    if len(text) <= max_chars:
        return text

    return text[:max_chars].rstrip() + "..."


def format_context_from_search_results(
    search_results: List[SearchResult],
    *,
    max_items: int = 5,
    max_chars_per_item: int = 2000,
) -> str:
    if not search_results:
        return ""

    blocks: list[str] = []

    for idx, result in enumerate(search_results[:max_items], start=1):
        article = result.article

        question = ""
        questions = getattr(article, "questions", None)
        if isinstance(questions, list) and questions:
            question = questions[0]

        text = _norm(getattr(article, "text", ""))
        text = _truncate(text, max_chars_per_item)

        source = _norm(getattr(article, "source", ""))
        author = _norm(getattr(article, "author", ""))
        link = _norm(getattr(article, "link", ""))
        post_date = _norm(getattr(article, "post_date", ""))
        created_at = _norm(getattr(article, "created_at", ""))

        block = (
            f"[资料 {idx}]\n"
            f"Q: {_norm(question)}\n"
            f"A: {text}\n"
            f"来源: {source}\n"
            f"链接: {link}\n"
            f"日期: {post_date}\n"
            f"检索分数: {result.score}\n"
            f"检索排名: {result.rank}"
        )

        blocks.append(block)

    return "\n\n".join(blocks)