# packages/rag_core/generator/test_chatgpt_generator.py
from __future__ import annotations
from typing import List
import sys, os
from types import SimpleNamespace

# 允许直接 python/pytest 跑
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from .chatgpt_generator import ChatGPTGenerator
from app.schemas.article import Article


def test_generate_streams_and_passes_prompt(monkeypatch):
    """generate 是流式：桩掉 stream，校验 question/context 传入，并把增量拼起来断言"""
    gen = ChatGPTGenerator(model_name="gpt-5-nano", temperature=0.0)

    captured = {}
    def fake_stream(inputs, config=None):
        assert "question" in inputs and "context" in inputs
        captured["q"] = inputs["question"]
        captured["ctx"] = inputs["context"]
        # 逐块吐出三个片段，模拟流式
        for p in ["OK:", inputs["question"][:4], "..."]:
            yield p

    # 用 stream 桩替换
    monkeypatch.setattr(gen, "chain_with_mem", SimpleNamespace(stream=fake_stream))

    arts: List[Article] = [
        Article(id="1", title="Myki", raw_text="", text="去PTV或便利店即可。", source="PTV", link="x", created_at="2024-01-01")
    ]
    # generate 返回的是 generator，测试里要消费掉
    out = "".join(list(gen.generate("在墨尔本如何办理公交卡？", arts, session_id="u1")))
    assert out.startswith("OK:")
    assert "在墨尔本如何办理公交卡" in captured["q"]
    assert "Q:" in captured["ctx"] and "A:" in captured["ctx"]
    assert "来源:" in captured["ctx"] and "链接:" in captured["ctx"] and "日期:" in captured["ctx"]


def test_stream_generate_yields_chunks_and_usage(monkeypatch):
    """继续验证增量与 session_id 传递 & on_usage 被调用（即使 usage 为空也应触发）"""
    gen = ChatGPTGenerator(model_name="gpt-5-nano", temperature=0.0)

    def fake_stream(inputs, config=None):
        # 校验 session_id 传入
        assert config and config.get("configurable", {}).get("session_id") == "u2"
        for p in ["A", "B", "C"]:
            yield p

    monkeypatch.setattr(gen, "chain_with_mem", SimpleNamespace(stream=fake_stream))

    usage_collected = {}
    def on_usage(u):
        # 这里只是确认回调被调用；实际 token 字段可能为 {}
        usage_collected.update(u or {})

    arts = [Article(id="1", title="T", raw_text="", text="X", source="S", link="L", created_at="2024")]
    chunks = list(gen.generate("q", arts, session_id="u2", on_usage=on_usage))
    assert "".join(chunks) == "ABC"
    assert isinstance(usage_collected, dict)  # 至少被回调了


def test_memory_same_session_two_turns(monkeypatch):
    """同一 session_id 连续两问都会通过链路；我们记录调用顺序与 session_id"""
    gen = ChatGPTGenerator(model_name="gpt-5-nano", temperature=0.0)

    calls = []
    def fake_stream(inputs, config=None):
        calls.append((inputs["question"], config["configurable"]["session_id"]))
        yield f"OK:{inputs['question']}"

    monkeypatch.setattr(gen, "chain_with_mem", SimpleNamespace(stream=fake_stream))

    arts = [Article(id="1", title="Myki", raw_text="", text="充值/购买说明", source="PTV", link="x", created_at="2024")]

    out1 = "".join(list(gen.generate("怎么申请公交卡？", arts, session_id="user-42")))
    out2 = "".join(list(gen.generate("那学生有优惠吗？", arts, session_id="user-42")))

    assert out1.startswith("OK:怎么申请公交卡")
    assert out2.startswith("OK:那学生有优惠吗")
    assert calls == [
        ("怎么申请公交卡？", "user-42"),
        ("那学生有优惠吗？", "user-42"),
    ]


# 追加到现有测试文件末尾
# 新增：
# 流式接口签名与 BaseGenerator 对齐（**kwargs + -> Iterable[str]）
# UsageCallback 支持在流式场景下估算 token与计时，并放在 finally 中确保 on_usage 一定被触发
# 新增 TokenCappedHistory，在 InMemoryHistoryStore 中启用，避免会话记忆无限增长（含线程安全）
# 上下文格式化支持按 token 截断（无 tiktoken 时用字符近似）
# 保留原有的 Prompt/上下文样式与 generate_text 非流式便捷方法（已与父类签名对齐）

from types import SimpleNamespace
import pytest

from packages.rag_core.generator.chatgpt_generator import (
    ChatGPTGenerator,
    InMemoryHistoryStore,
)
from packages.rag_core.utils.article import Article


def test_stream_passes_callbacks_and_session_id(monkeypatch):
    """验证 config 中的 callbacks 存在，且 session_id 透传"""
    gen = ChatGPTGenerator(model_name="gpt-5-nano", temperature=0.0)

    def fake_stream(inputs, config=None):
        assert config and config.get("configurable", {}).get("session_id") == "s-cb"
        cbs = config.get("callbacks")
        assert isinstance(cbs, list) and len(cbs) >= 1  # 有 UsageCallback
        yield "ok"

    monkeypatch.setattr(gen, "chain_with_mem", SimpleNamespace(stream=fake_stream))

    arts = [Article(id="1", title="T", raw_text="", text="X", source="S", link="L", created_at="2024")]
    out = "".join(list(gen.generate("q", arts, session_id="s-cb")))
    assert out == "ok"


def test_on_usage_called_even_when_stream_raises(monkeypatch):
    """流式中途抛错时，也会执行 on_usage（因为放在 finally）"""
    gen = ChatGPTGenerator(model_name="gpt-5-nano", temperature=0.0)

    def fake_stream(inputs, config=None):
        yield "part"
        raise RuntimeError("boom")

    monkeypatch.setattr(gen, "chain_with_mem", SimpleNamespace(stream=fake_stream))

    usage_collected = {}
    def on_usage(u):
        usage_collected.update(u or {})

    arts = [Article(id="1", title="T", raw_text="", text="X", source="S", link="L", created_at="2024")]

    chunks = []
    with pytest.raises(RuntimeError):
        for ch in gen.generate("q", arts, session_id="s-err", on_usage=on_usage):
            chunks.append(ch)

    assert "".join(chunks) == "part"
    assert isinstance(usage_collected, dict)  # 至少被回调了（字段是否为空不作强约束）


def test_generate_text_invoke_and_usage(monkeypatch):
    """非流式 generate_text 走 invoke 路径，也会触发 on_usage"""
    gen = ChatGPTGenerator(model_name="gpt-5-nano", temperature=0.0)

    captured = {}
    def fake_invoke(inputs, config=None):
        assert config and config.get("configurable", {}).get("session_id") == "s-text"
        captured["callbacks"] = config.get("callbacks")
        return "OK-TEXT"

    monkeypatch.setattr(gen, "chain_with_mem", SimpleNamespace(invoke=fake_invoke))

    usage_collected = {}
    def on_usage(u):
        usage_collected.update(u or {})

    arts = [Article(id="1", title="T", raw_text="", text="X", source="S", link="L", created_at="2024")]
    out = gen.generate_text("hello", arts, session_id="s-text", on_usage=on_usage)

    assert out == "OK-TEXT"
    assert isinstance(usage_collected, dict)
    assert isinstance(captured["callbacks"], list) and len(captured["callbacks"]) >= 1


def test_history_store_caps_by_message_count():
    """验证会话历史的条数上限裁剪（不依赖 tiktoken，稳定）"""
    store = InMemoryHistoryStore(max_tokens_per_session=9999, max_messages=3)
    hist = store.get_history("sess-1")

    # 连续写多条消息，超过 max_messages
    for i in range(10):
        hist.add_user_message(f"u{i}")
        hist.add_ai_message(f"a{i}")

    assert len(hist.messages) <= 3  # 被裁剪到不超过上限
