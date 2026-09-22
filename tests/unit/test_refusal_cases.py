"""The refusal cases stay relevant-but-answerless.

The contract suite only runs by hand, but its inputs are checked on every
push. A case whose context has drifted into containing the answer would pass
the contract for the wrong reason, and a case whose context no longer
mentions what the question is about would be the easy, unrelated kind the
issue warns against (#103). Both are mechanical to check, so they are.

Nothing here calls OpenAI.
"""

import pytest

from app.core.config import rag_config
from app.services.rag.eval.refusal import mentions
from app.services.rag.generator.context_formatter import (
    format_context_from_search_results,
)
from tests.generator_contract.cases import evidence_for, load_cases

CASES = load_cases()


def rendered(case) -> str:
    """The context as the production generator config would show it."""
    context = rag_config["generator"].get("context", {})
    return format_context_from_search_results(
        case.search_results(),
        max_items=context.get("max_items", 5),
        max_chars_per_item=context.get("max_chars_per_item", 2000),
    )


def test_there_are_at_least_twenty_cases():
    # Fewer would weaken the release gate quietly: dropping the case that
    # fails is the easiest way to get a green run.
    assert len(CASES) >= 20


def test_case_ids_are_unique():
    ids = [case.id for case in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_context_is_about_what_the_question_asks(case):
    shown = rendered(case)

    assert case.context and case.anchors and case.why.strip()
    missing = [anchor for anchor in case.anchors if not mentions(shown, anchor)]
    assert not missing, f"context never mentions {missing}"


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_context_does_not_contain_the_withheld_answer(case):
    stored = "\n".join(item["text"] for item in case.context)

    for term in case.withheld:
        assert not mentions(stored, term), f"{term!r} is in the context"
        assert not mentions(rendered(case), term), f"{term!r} is in the context"
        # A correct refusal may repeat the question, so a withheld term in
        # the question would fail an answer that did nothing wrong.
        assert not mentions(case.query, term), f"{term!r} is in the question"


def test_evidence_drops_only_the_formatters_own_numbering():
    case = CASES[0]
    shown = rendered(case)

    evidence = evidence_for(case.query, shown)

    # If context_formatter renames these lines, the pattern in cases.py stops
    # matching and "[资料 3]" starts counting as material again.
    assert "[资料" in shown and "检索分数" in shown and "检索排名" in shown
    assert "[资料" not in evidence
    assert "检索分数" not in evidence
    assert "检索排名" not in evidence
    assert case.query in evidence
    for item in case.context:
        assert item["link"] in evidence
