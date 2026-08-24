"""Invariants of the shipped `rag-config.yaml`.

Every assertion here relates two numbers that live in *different* sections of
one file. That kind of mismatch raises nothing and logs nothing — it just
returns quietly worse answers, which is why it survives review. ROADMAP_rag.md
0.3 is the case in point: retriever `top_k=5` feeding a reranker that keeps 3
shipped for months, and no test failed.
"""

from app.core.config import rag_config
from app.main import ChatRequest


RETRIEVER = rag_config["retriever"]
RERANKER = rag_config["reranker"]
CONTEXT = rag_config["generator"]["context"]


def _api_upper_bound(field_name: str) -> int:
    """The `le=` bound Pydantic recorded for a `ChatRequest` field."""
    for constraint in ChatRequest.model_fields[field_name].metadata:
        upper = getattr(constraint, "le", None)
        if upper is not None:
            return upper

    raise AssertionError(f"ChatRequest.{field_name} declares no upper bound")


def test_retriever_pool_is_deep_enough_for_reranking_to_mean_anything():
    # A cross-encoder earns its per-request CPU by picking the right document
    # out of *tens* of candidates. At the old top_k=5 it could only discard 2
    # of 5, so it was paying full price for almost no ranking (ROADMAP_rag 0.3).
    assert RETRIEVER["top_k"] >= 10


def test_reranker_discards_more_than_it_keeps():
    # If the pool is not larger than what survives, rerank() degenerates into a
    # sort of everything the retriever already returned.
    assert RERANKER["top_k"] < RETRIEVER["top_k"]


def test_reranker_output_exactly_fills_the_generator_context():
    # Two silent failures, one assertion. Keep more than max_items and
    # format_context_from_search_results() slices the extras away after the
    # cross-encoder already paid for them; keep fewer and the generator is
    # handed context slots that are simply left empty, which is what a
    # reranker top_k of 3 against max_items of 5 was doing.
    assert RERANKER["top_k"] == CONTEXT["max_items"]


def test_shipped_defaults_are_expressible_over_the_api():
    # A caller must be able to ask for the default explicitly, e.g. to
    # reproduce a recorded interaction. If the config default were to exceed
    # ChatRequest's bound, `{"top_k": <default>}` would 422.
    assert RETRIEVER["top_k"] <= _api_upper_bound("top_k")
    assert RERANKER["top_k"] <= _api_upper_bound("rerank_top_k")
