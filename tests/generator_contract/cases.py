"""Loading the refusal cases, and what the model was entitled to use.

The cases themselves live in refusal_cases.yaml, next to this file; the
header there explains how they were built. This module is shared by the
contract test, which sends them to OpenAI, and by
tests/unit/test_refusal_cases.py, which checks on every push that each one is
still relevant-but-answerless.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.schemas.article import Article
from app.schemas.search_result import SearchResult

CASES_PATH = Path(__file__).with_name("refusal_cases.yaml")

# Lines context_formatter adds around each item. They are the formatter's
# numbering, not material: "[资料 3]" and "检索排名: 3" must not make the
# number 3 count as something the answer could have got from the context.
_SCAFFOLDING = re.compile(r"^(?:\[资料 \d+\]|检索分数: .*|检索排名: .*)$", re.MULTILINE)


@dataclass(frozen=True)
class RefusalCase:
    id: str
    query: str
    why: str
    anchors: tuple[str, ...]
    withheld: tuple[str, ...]
    context: tuple[dict[str, Any], ...]

    def search_results(self) -> list[SearchResult]:
        """The context as the reranker would hand it to the generator."""
        return [
            SearchResult(
                article=Article(
                    id=f"{self.id}#{rank}",
                    text=item["text"],
                    questions=[item["question"]],
                    source=item["source"],
                    link=item["link"],
                    post_date=item.get("post_date"),
                ),
                score=round(1 - rank / 10, 2),
                rank=rank,
            )
            for rank, item in enumerate(self.context, start=1)
        ]


def load_cases(path: Path = CASES_PATH) -> list[RefusalCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        RefusalCase(
            id=case["id"],
            query=case["query"],
            why=case["why"],
            anchors=tuple(case["anchors"]),
            withheld=tuple(case.get("withheld") or ()),
            context=tuple(case["context"]),
        )
        for case in raw["cases"]
    ]


def evidence_for(query: str, rendered_context: str) -> str:
    """Everything a fact in the answer may legitimately come from.

    That is the context exactly as the model was shown it -- after the
    formatter's truncation, so a fact cut off at max_chars_per_item does not
    count as available -- plus the question, which the answer may echo.
    """
    return f"{query}\n{_SCAFFOLDING.sub('', rendered_context)}"
