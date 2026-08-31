import ast
import logging
from pathlib import Path

from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.core.logging import AppJsonLogFormatter
from app.services.rag.adapters.langchain_adapter import LangChainRAGAdapter

_LOGGER_NAME = "app.services.rag.adapters.langchain_adapter"


class FakeRetriever:
    def search(self, query, top_k=5):
        return [
            SearchResult(
                article=Article(text="retrieved", questions=[query]),
                score=0.5,
                rank=1,
            )
        ][:top_k]


class FakeReranker:
    def rerank(self, query, search_results, top_k=3):
        result = search_results[0].model_copy(update={"score": 0.9, "rank": 1})
        return [result][:top_k]


class FakeGenerator:
    def generate_text(self, query, search_results, chat_history=None):
        return f"answer:{query}:{len(search_results)}:{len(chat_history or [])}"


class DummyRetriever:
    def __init__(self, results):
        self._results = results

    def search(self, query, **kwargs):
        return self._results


class DummyReranker:
    def __init__(self, results):
        self._results = results

    def rerank(self, query, search_results, **kwargs):
        return self._results


def _result(doc_id, score, rank):
    return SearchResult(
        article=Article(id=doc_id, text="content", questions=["q"]),
        score=score,
        rank=rank,
    )


def test_retriever_runnable_wraps_retriever_only():
    runnable = LangChainRAGAdapter.retriever_runnable(FakeRetriever())

    state = runnable.invoke({"query": "hello", "top_k": 5})

    assert state["query"] == "hello"
    assert state["search_results"][0].score == 0.5


def test_reranker_runnable_wraps_reranker_only():
    search_results = FakeRetriever().search("hello")
    runnable = LangChainRAGAdapter.reranker_runnable(FakeReranker())

    state = runnable.invoke(
        {"query": "hello", "search_results": search_results, "rerank_top_k": 3}
    )

    assert state["search_results"][0].score == 0.9


def test_generator_runnable_wraps_generator_only():
    search_results = FakeRetriever().search("hello")
    runnable = LangChainRAGAdapter.generator_runnable(FakeGenerator())

    state = runnable.invoke(
        {
            "query": "hello",
            "search_results": search_results,
            "chat_history": [{"role": "user", "content": "earlier"}],
        }
    )

    assert state["answer"] == "answer:hello:1:1"


def test_core_components_do_not_import_langchain():
    root = Path(__file__).parents[2] / "app" / "services" / "rag"
    core_dirs = [root / "retriever", root / "reranker", root / "generator"]

    offenders = []
    for directory in core_dirs:
        for path in directory.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                else:
                    continue
                if any(module.startswith("langchain") for module in modules):
                    offenders.append(path.name)

    assert offenders == []


def test_retrieve_logs_doc_ids_scores_and_ranks_in_order(caplog):
    results = [
        _result("wx_a", 0.9, 1),
        _result("wx_b", 0.8, 2),
        _result("wx_c", 0.7, 3),
    ]
    retriever = DummyRetriever(results)

    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        LangChainRAGAdapter.retriever_runnable(retriever).invoke(
            {"query": "student visa", "top_k": None}
        )

    records = [r for r in caplog.records if r.message == "Retrieved candidates"]
    assert len(records) == 1
    record = records[0]
    assert record.stage == "retrieve"
    assert record.results == [
        {"doc_id": "wx_a", "score": 0.9, "rank": 1},
        {"doc_id": "wx_b", "score": 0.8, "rank": 2},
        {"doc_id": "wx_c", "score": 0.7, "rank": 3},
    ]


def test_rerank_logs_doc_ids_scores_and_ranks_in_order(caplog):
    # Order intentionally differs from retrieval to prove the log reflects
    # the reranker's own output order, not the retriever's.
    results = [
        _result("wx_b", 0.8, 1),
        _result("wx_a", 0.9, 2),
    ]
    reranker = DummyReranker(results)

    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        LangChainRAGAdapter.reranker_runnable(reranker).invoke(
            {
                "query": "student visa",
                "search_results": [],
                "rerank_top_k": None,
            }
        )

    records = [r for r in caplog.records if r.message == "Reranked candidates"]
    assert len(records) == 1
    record = records[0]
    assert record.stage == "rerank"
    assert record.results == [
        {"doc_id": "wx_b", "score": 0.8, "rank": 1},
        {"doc_id": "wx_a", "score": 0.9, "rank": 2},
    ]


def test_retrieve_log_payload_never_contains_the_query_text(caplog):
    results = [_result("wx_a", 0.9, 1)]
    retriever = DummyRetriever(results)

    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        LangChainRAGAdapter.retriever_runnable(retriever).invoke(
            {"query": "how do I apply for oshc", "top_k": None}
        )

    record = next(r for r in caplog.records if r.message == "Retrieved candidates")
    assert not hasattr(record, "query")

    formatted = AppJsonLogFormatter().format(record)
    assert "oshc" not in formatted


def test_rerank_log_payload_never_contains_the_query_text(caplog):
    results = [_result("wx_a", 0.9, 1)]
    reranker = DummyReranker(results)

    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        LangChainRAGAdapter.reranker_runnable(reranker).invoke(
            {
                "query": "how do I apply for oshc",
                "search_results": [],
                "rerank_top_k": None,
            }
        )

    record = next(r for r in caplog.records if r.message == "Reranked candidates")
    assert not hasattr(record, "query")

    formatted = AppJsonLogFormatter().format(record)
    assert "oshc" not in formatted
