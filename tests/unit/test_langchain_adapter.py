import ast
from pathlib import Path

from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.adapters.langchain_adapter import LangChainRAGAdapter


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

    def stream_text(self, query, search_results, chat_history=None):
        yield "answer:"
        yield query


def test_chain_returns_full_pipeline_state():
    adapter = LangChainRAGAdapter(FakeRetriever(), FakeGenerator(), FakeReranker())

    state = adapter.invoke({
        "query": "hello",
        "top_k": 5,
        "rerank_top_k": 3,
        "chat_history": [{"role": "user", "content": "earlier"}],
    })

    assert state["answer"] == "answer:hello:1:1"
    assert state["search_results"][0].score == 0.9
    assert state["query"] == "hello"


def test_adapter_can_skip_reranker_and_stream_full_pipeline():
    adapter = LangChainRAGAdapter(FakeRetriever(), FakeGenerator())

    state = adapter.invoke({"query": "hello"})
    chunks = list(adapter.stream({"query": "hello"}))

    assert state["search_results"][0].score == 0.5
    assert chunks == ["answer:", "hello"]


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
