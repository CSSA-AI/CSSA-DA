from fastapi.testclient import TestClient

from app.api.deps import get_rag_orchestrator
from app.main import app
from app.schemas.article import Article
from app.schemas.search_result import SearchResult


class StubOrchestrator:
    def run(self, query, **kwargs):
        return (
            f"Answer for: {query}",
            [
                SearchResult(
                    article=Article(
                        text="Relevant article",
                        questions=["Example question"],
                        source="test",
                        link="https://example.com/article",
                    ),
                    score=0.95,
                    rank=1,
                )
            ],
        )


def client() -> TestClient:
    app.dependency_overrides[get_rag_orchestrator] = lambda: StubOrchestrator()
    return TestClient(app)


def test_health():
    response = client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_returns_answer_and_sources():
    response = client().post(
        "/chat",
        json={
            "message": "How do I enrol?",
            "chat_history": [{"role": "user", "content": "Hello"}],
            "top_k": 5,
            "rerank_top_k": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "Answer for: How do I enrol?"
    assert payload["sources"][0]["article"]["source"] == "test"
    assert payload["sources"][0]["score"] == 0.95


def test_chat_rejects_an_empty_message():
    response = client().post("/chat", json={"message": ""})

    assert response.status_code == 422
