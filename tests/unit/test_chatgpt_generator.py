from __future__ import annotations

from types import SimpleNamespace
import pytest

from app.services.rag.generator.chatgpt_generator import (
    ChatGPTGenerator,
    InMemoryHistoryStore,
)
from app.schemas.article import Article
from app.schemas.search_result import SearchResult


def _sr(
    *,
    article_id: str = "1",
    question: str = "Myki 怎么办理？",
    text: str = "去PTV或便利店即可。",
    source: str = "PTV",
    link: str = "x",
    score: float = 1.0,
) -> SearchResult:
    article = Article(
        id=article_id,
        text=text,
        questions=[question],   # 关键：必须非空，否则 generator 会 fallback 到 art.title
        source=source,
        link=link,
    )
    return SearchResult(article=article, score=score)


def test_generate_streams_and_passes_prompt(monkeypatch):
    gen = ChatGPTGenerator(model_name="gpt-5-nano", temperature=0.0)

    captured = {}

    def fake_stream(inputs, config=None):
        assert "question" in inputs and "context" in inputs
        captured["q"] = inputs["question"]
        captured["ctx"] = inputs["context"]
        for p in ["OK:", inputs["question"][:4], "..."]:
            yield p

    monkeypatch.setattr(gen, "chain_with_mem", SimpleNamespace(stream=fake_stream))

    results = [_sr()]
    out = "".join(list(gen.generate("在墨尔本如何办理公交卡？", results, session_id="u1")))

    assert out.startswith("OK:")
    assert "在墨尔本如何办理公交卡" in captured["q"]
    assert "Q:" in captured["ctx"]
    assert "A:" in captured["ctx"]
    assert "来源:" in captured["ctx"]
    assert "链接:" in captured["ctx"]
    assert "日期:" in captured["ctx"]


def test_stream_generate_yields_chunks_and_usage(monkeypatch):
    gen = ChatGPTGenerator(model_name="gpt-5-nano", temperature=0.0)

    def fake_stream(inputs, config=None):
        assert config is not None
        assert config.get("configurable", {}).get("session_id") == "u2"
        for p in ["A", "B", "C"]:
            yield p

    monkeypatch.setattr(gen, "chain_with_mem", SimpleNamespace(stream=fake_stream))

    usage_called = {"called": False}
    usage_payload = {}

    def on_usage(u):
        usage_called["called"] = True
        usage_payload.update(u or {})

    results = [_sr(question="T", text="X", source="S", link="L")]
    chunks = list(gen.generate("q", results, session_id="u2", on_usage=on_usage))

    assert "".join(chunks) == "ABC"
    assert usage_called["called"] is True
    assert isinstance(usage_payload, dict)


def test_memory_same_session_two_turns(monkeypatch):
    gen = ChatGPTGenerator(model_name="gpt-5-nano", temperature=0.0)

    calls = []

    def fake_stream(inputs, config=None):
        calls.append((inputs["question"], config["configurable"]["session_id"]))
        yield f"OK:{inputs['question']}"

    monkeypatch.setattr(gen, "chain_with_mem", SimpleNamespace(stream=fake_stream))

    results = [_sr(question="Myki 怎么办理？", text="充值/购买说明")]

    out1 = "".join(list(gen.generate("怎么申请公交卡？", results, session_id="user-42")))
    out2 = "".join(list(gen.generate("那学生有优惠吗？", results, session_id="user-42")))

    assert out1.startswith("OK:怎么申请公交卡")
    assert out2.startswith("OK:那学生有优惠吗")
    assert calls == [
        ("怎么申请公交卡？", "user-42"),
        ("那学生有优惠吗？", "user-42"),
    ]


def test_stream_passes_callbacks_and_session_id(monkeypatch):
    gen = ChatGPTGenerator(model_name="gpt-5-nano", temperature=0.0)

    def fake_stream(inputs, config=None):
        assert config is not None
        assert config.get("configurable", {}).get("session_id") == "s-cb"
        cbs = config.get("callbacks")
        assert isinstance(cbs, list)
        assert len(cbs) >= 1
        yield "ok"

    monkeypatch.setattr(gen, "chain_with_mem", SimpleNamespace(stream=fake_stream))

    results = [_sr(question="T", text="X", source="S", link="L")]
    out = "".join(list(gen.generate("q", results, session_id="s-cb")))

    assert out == "ok"


def test_on_usage_called_even_when_stream_raises(monkeypatch):
    gen = ChatGPTGenerator(model_name="gpt-5-nano", temperature=0.0)

    def fake_stream(inputs, config=None):
        yield "part"
        raise RuntimeError("boom")

    monkeypatch.setattr(gen, "chain_with_mem", SimpleNamespace(stream=fake_stream))

    usage_called = {"called": False}
    usage_payload = {}

    def on_usage(u):
        usage_called["called"] = True
        usage_payload.update(u or {})

    results = [_sr(question="T", text="X", source="S", link="L")]

    chunks = []
    with pytest.raises(RuntimeError):
        for ch in gen.generate("q", results, session_id="s-err", on_usage=on_usage):
            chunks.append(ch)

    assert "".join(chunks) == "part"
    assert usage_called["called"] is True
    assert isinstance(usage_payload, dict)


def test_generate_text_invoke_and_usage(monkeypatch):
    gen = ChatGPTGenerator(model_name="gpt-5-nano", temperature=0.0)

    captured = {}

    def fake_invoke(inputs, config=None):
        assert config is not None
        assert config.get("configurable", {}).get("session_id") == "s-text"
        captured["callbacks"] = config.get("callbacks")
        return "OK-TEXT"

    monkeypatch.setattr(gen, "chain_with_mem", SimpleNamespace(invoke=fake_invoke))

    usage_called = {"called": False}
    usage_payload = {}

    def on_usage(u):
        usage_called["called"] = True
        usage_payload.update(u or {})

    results = [_sr(question="T", text="X", source="S", link="L")]
    out = gen.generate_text("hello", results, session_id="s-text", on_usage=on_usage)

    assert out == "OK-TEXT"
    assert usage_called["called"] is True
    assert isinstance(usage_payload, dict)
    assert isinstance(captured["callbacks"], list)
    assert len(captured["callbacks"]) >= 1


def test_history_store_caps_by_message_count():
    store = InMemoryHistoryStore(max_tokens_per_session=9999, max_messages=3)
    hist = store.get_history("sess-1")

    for i in range(10):
        hist.add_user_message(f"u{i}")
        hist.add_ai_message(f"a{i}")

    assert len(hist.messages) <= 3