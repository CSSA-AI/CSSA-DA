import sys
from types import SimpleNamespace

from app.api import deps


class FakePGVectorRetriever:
    pass


class FakeReranker:
    pass


class FakeGenerator:
    pass


def test_default_rag_orchestrator_uses_pgvector_retriever(monkeypatch):
    deps._build_rag_orchestrator.cache_clear()
    monkeypatch.setitem(
        sys.modules,
        "app.services.rag.retriever.pg_retriever",
        SimpleNamespace(PGVectorRetriever=FakePGVectorRetriever),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.rag.reranker.cross_encoder_reranker",
        SimpleNamespace(CrossEncoderReranker=FakeReranker),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.rag.generator.chatgpt_generator",
        SimpleNamespace(ChatGPTGenerator=FakeGenerator),
    )

    try:
        orchestrator = deps._build_rag_orchestrator()

        assert isinstance(orchestrator.retriever, FakePGVectorRetriever)
        assert isinstance(orchestrator.reranker, FakeReranker)
        assert isinstance(orchestrator.generator, FakeGenerator)
    finally:
        deps._build_rag_orchestrator.cache_clear()
