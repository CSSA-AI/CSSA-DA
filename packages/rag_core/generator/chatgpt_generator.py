# 下面是改进后的 chatgpt_generator.py，已把所有关键改动合并好：
# 流式接口签名与 BaseGenerator 对齐（**kwargs + -> Iterable[str]）
# UsageCallback 支持在流式场景下估算 token与计时，并放在 finally 中确保 on_usage 一定被触发
# 新增 TokenCappedHistory，在 InMemoryHistoryStore 中启用，避免会话记忆无限增长（含线程安全）
# 上下文格式化支持按 token 截断（无 tiktoken 时用字符近似）
# 保留你原有的 Prompt/上下文样式与 generate_text 非流式便捷方法（已与父类签名对齐）

# -*- coding: utf-8 -*-
# packages/rag_core/generator/chatgpt_generator.py

from __future__ import annotations
from typing import List, Dict, Optional, Callable, Iterable
import os
import time
import json
import threading

from dotenv import load_dotenv

from .base import BaseGenerator
from packages.rag_core.utils.article import Article

# LangChain 现代用法
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.callbacks import BaseCallbackHandler


# ========== 环境 ==========
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# 不在此处强制报错，便于测试时 monkeypatch 链条；真正调用到 LLM 再说


# ========== 工具函数：Token 估算 / 截断 / Prompt 预览 ==========
def _estimate_tokens(text: str, model: str = "gpt-5-nano") -> int:
    """优先用 tiktoken 估算；若不可用则用“约4字符≈1 token”的近似。"""
    try:
        import tiktoken
        try:
            enc = tiktoken.encoding_for_model(model)
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text or ""))
    except Exception:
        return max(1, len(text or "") // 4)


def _truncate_by_tokens(text: str, max_tokens: int, model: str = "gpt-5-nano") -> str:
    """按 token 截断文本；无 tiktoken 时降级为按字符近似。"""
    if not text:
        return ""
    try:
        import tiktoken
        try:
            enc = tiktoken.encoding_for_model(model)
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")
        ids = enc.encode(text)
        if len(ids) <= max_tokens:
            return text
        return enc.decode(ids[:max_tokens])
    except Exception:
        # 4 字符 ≈ 1 token 的近似
        approx_chars = max_tokens * 4
        return text[:approx_chars]


def _prompt_preview(prompt: ChatPromptTemplate, inputs: Dict) -> str:
    """
    将 ChatPromptTemplate + inputs 渲染为纯文本，便于用于 token 估算等。
    """
    try:
        msgs = prompt.format_messages(**inputs)
        return "\n".join(getattr(m, "content", "") for m in msgs if hasattr(m, "content"))
    except Exception:
        try:
            return prompt.format(**inputs)  # 某些版本下可用
        except Exception:
            return f"用户问题: {inputs.get('question','')}\n资料:\n{inputs.get('context','')}"


# ========== 用量监测回调（流式友好，带估算兜底） ==========
class UsageCallback(BaseCallbackHandler):
    """统计本次调用的 tokens 与耗时；回传给上层 on_usage 回调（流式场景做估算兜底）。"""
    def __init__(self, prompt_text_getter: Optional[Callable[[], str]] = None, model_name: str = "gpt-5-nano"):
        self._started_at: Optional[float] = None
        self._completion_accum: List[str] = []
        self.usage: Dict = {}
        self._prompt_text_getter = prompt_text_getter
        self._model_name = model_name

    # LLM 生命周期
    def on_llm_start(self, *args, **kwargs):
        self._started_at = time.time()
        self._completion_accum.clear()

    def on_llm_new_token(self, token: str, **kwargs):
        # 流式时累计 completion 文本，用于兜底估算
        if token:
            self._completion_accum.append(token)

    def on_llm_end(self, response, **kwargs):
        elapsed = time.time() - (self._started_at or time.time())
        usage = {}
        try:
            # 兼容不同 SDK 回包结构（非流式时更可能拿到）
            usage = (response.llm_output or {}).get("token_usage", {}) or {}
        except Exception:
            usage = {}

        if not usage:
            # 兜底估算
            prompt_text = ""
            if callable(self._prompt_text_getter):
                try:
                    prompt_text = self._prompt_text_getter() or ""
                except Exception:
                    prompt_text = ""
            completion_text = "".join(self._completion_accum)
            p = _estimate_tokens(prompt_text, self._model_name)
            c = _estimate_tokens(completion_text, self._model_name)
            usage = {"prompt_tokens": p, "completion_tokens": c, "total_tokens": (p + c)}

        self.usage = {**usage, "elapsed_sec": round(elapsed, 3)}


# ========== Token 上限的会话历史（自动裁剪） ==========
def _stringify_content(c) -> str:
    if isinstance(c, str):
        return c
    try:
        return json.dumps(c, ensure_ascii=False)
    except Exception:
        return str(c)


def _approx_tokens_of_messages(messages, model_name: str = "gpt-5-nano") -> int:
    try:
        import tiktoken
        try:
            enc = tiktoken.encoding_for_model(model_name)
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")
        text = "\n".join(_stringify_content(getattr(m, "content", "")) for m in messages)
        return len(enc.encode(text))
    except Exception:
        text = "\n".join(_stringify_content(getattr(m, "content", "")) for m in messages)
        return max(1, len(text) // 4)


class TokenCappedHistory(ChatMessageHistory):
    """
    继承 ChatMessageHistory，在每次写入后做 token/条数裁剪。
    - max_tokens: 会话历史 token 预算
    - max_messages: 额外的条数上限（可选）
    - model_name: 用于 tiktoken 选择编码
    """
    def __init__(self, max_tokens: int = 800, model_name: str = "gpt-5-nano", max_messages: int | None = None):
        super().__init__()
        self._max_tokens = max_tokens
        self._model_name = model_name
        self._max_messages = max_messages

    def _trim(self):
        # 条数优先（如果设置了）
        if self._max_messages is not None:
            while len(self.messages) > self._max_messages:
                self.messages.pop(0)

        # 再按 token 裁剪
        while len(self.messages) > 2 and _approx_tokens_of_messages(self.messages, self._model_name) > self._max_tokens:
            # 丢弃最早的一条（可按需改为“一问一答成对丢弃”或“摘要旧消息”）
            self.messages.pop(0)

    # 兼容不同版本签名：用 *args/**kwargs 透传
    def add_user_message(self, *args, **kwargs):
        super().add_user_message(*args, **kwargs)
        self._trim()

    def add_ai_message(self, *args, **kwargs):
        super().add_ai_message(*args, **kwargs)
        self._trim()

    def add_message(self, *args, **kwargs):
        super().add_message(*args, **kwargs)
        self._trim()


# ========== 简单的会话历史存储（按 session_id 隔离，带线程安全） ==========
class InMemoryHistoryStore:
    def __init__(self, *, max_tokens_per_session: int = 800, model_name: str = "gpt-5-nano", max_messages: int | None = None):
        self._store: Dict[str, TokenCappedHistory] = {}
        self._lock = threading.RLock()
        self._max_tokens = max_tokens_per_session
        self._model_name = model_name
        self._max_messages = max_messages

    def get_history(self, session_id: str) -> TokenCappedHistory:
        with self._lock:
            if session_id not in self._store:
                self._store[session_id] = TokenCappedHistory(
                    max_tokens=self._max_tokens,
                    model_name=self._model_name,
                    max_messages=self._max_messages,
                )
            return self._store[session_id]


# ========== 工具函数：保持原来的 context 格式（按 token 截断） ==========
def _norm(s: str | None) -> str:
    """把 None -> ''，并做简单空白清理。"""
    if not s:
        return ""
    return " ".join(str(s).split()).strip()


def _format_context_from_articles(
    articles: List[Article],
    *,
    max_answer_tokens: int = 800,    # 防止上下文过长（按 token）
    max_question_tokens: int = 60,
    model_for_token: str = "gpt-5-nano",
) -> str:
    """
    将 Article 列表格式化为给 LLM 的上下文字符串，保持 Q/A/来源/链接/日期 的样式。
    - Q:  questions[0] -> title
    - A:  text -> raw_text -> summary()
    - 来源: source -> author
    - 日期: created_at -> post_date
    - 链接: link
    会做 None 防护与 token 截断。
    """
    if not articles:
        return ""

    blocks: list[str] = []

    for art in articles:
        # Q
        q = None
        if isinstance(art.questions, list) and art.questions:
            q = art.questions[0]
        q = _norm(q or art.title)
        if q:
            q = _truncate_by_tokens(q, max_question_tokens, model_for_token)

        # A
        atext = _norm(getattr(art, "text", "")) or _norm(getattr(art, "raw_text", ""))
        if not atext:
            try:
                atext = _norm(art.summary(length=max_answer_tokens * 4))  # 近似：1 token ≈ 4 char
            except Exception:
                atext = ""
        if atext:
            atext = _truncate_by_tokens(atext, max_answer_tokens, model_for_token)

        # 其它字段
        source = _norm(getattr(art, "source", "")) or _norm(getattr(art, "author", ""))
        link = _norm(getattr(art, "link", ""))
        date = _norm(getattr(art, "created_at", "")) or _norm(getattr(art, "post_date", ""))

        block = (
            f"Q: {q}\n"
            f"A: {atext}\n"
            f"来源: {source}\n"
            f"链接: {link}\n"
            f"日期: {date}"
        )
        blocks.append(block)

    return "\n\n".join(blocks)


# ========== ChatGPTGenerator 实现 ==========
class ChatGPTGenerator(BaseGenerator):
    """
    继承 BaseGenerator，保持你原有的 prompt/context 结构，
    并接入对话记忆（按 session_id）与 API 用量监测。
    """

    def __init__(
        self,
        model_name: str = "gpt-5-nano",
        temperature: float = 0.3,
        max_retries: int = 2,
        history_store: Optional[InMemoryHistoryStore] = None,
    ):
        # 保存模型名供其它功能（token 估算/历史裁剪）使用
        self.model_name = model_name

        # 底层 LLM
        self.llm = ChatOpenAI(
            api_key=OPENAI_API_KEY,
            model=model_name,
            temperature=temperature,
            streaming=True,      # 允许底层流式
            max_retries=max_retries,
            # 注意：不同版本的 langchain_openai 可能不支持 stream_usage/extra_body；在此不强行设置，避免兼容性问题
            # 如果版本支持，可在外部配置中开启：extra_body={"stream_options": {"include_usage": True}}
        )

        # —— 保持原有 Prompt 内容（不引入额外变量以避免破坏兼容） ——
        self.prompt = ChatPromptTemplate.from_messages([
            ("system",
             "你是一名友好、知识丰富的CSSA智能助手, 专门为在澳洲的留学生提供建议。"
             "请根据以下资料，结合你的知识，准确回答用户问题，并保持简洁、清晰、有礼貌。"
             "如涉及实用信息, 请尽量引用来源(source)和链接(link)。"
             "请用留学生能理解的卖萌语气回答，不要编造信息。"),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human",
             "用户问题: {question}\n"
             "资料:\n{context}")
        ])

        # —— LCEL：prompt → llm → 解析为 str ——
        self.base_chain = self.prompt | self.llm | StrOutputParser()

        # —— 会话历史仓库（按 session_id 区分；默认带 token 上限） ——
        self.history_store = history_store or InMemoryHistoryStore(
            max_tokens_per_session=800,
            model_name=model_name,
            max_messages=None,  # 可按需设置条数上限
        )

        def _get_history(session_id: str) -> BaseChatMessageHistory:
            return self.history_store.get_history(session_id)

        # —— 绑定记忆：把 chat_history 注入到 MessagesPlaceholder 中 ——
        self.chain_with_mem = RunnableWithMessageHistory(
            self.base_chain,
            _get_history,
            input_messages_key="question",      # 只把 question 当成“人类输入”写入历史
            history_messages_key="chat_history" # 历史插槽
        )

    # base.py 的要求：generate(self, query: str, articles: list[Article], **kwargs) -> Iterable[str]
    def generate(
        self,
        query: str,
        articles: List[Article],
        *,
        session_id: str = "default",
        on_usage: Optional[Callable[[Dict], None]] = None,
        **kwargs,
    ) -> Iterable[str]:
        """
        逐字/逐块流式生成。yield 出文本增量；末尾（finally）触发 on_usage。
        """
        context_str = _format_context_from_articles(
            articles,
            max_answer_tokens=800,
            max_question_tokens=60,
            model_for_token=self.model_name,
        )
        inputs = {"question": query, "context": context_str}

        usage_cb = UsageCallback(
            prompt_text_getter=lambda: _prompt_preview(self.prompt, inputs),
            model_name=self.model_name,
        )

        stream = self.chain_with_mem.stream(
            inputs,
            config={
                "configurable": {"session_id": session_id},
                "callbacks": [usage_cb],
            },
        )

        try:
            for piece in stream:
                # 直接逐块吐出给上层
                yield piece
        finally:
            if on_usage:
                on_usage(usage_cb.usage or {})

    # 可选：非流式一次性完整答案（保留并与父类签名对齐）
    def generate_text(
        self,
        query: str,
        articles: List[Article],
        *,
        session_id: str = "default",
        on_usage: Optional[Callable[[Dict], None]] = None,
        **kwargs,
    ) -> str:
        """
        返回一次性完整答案字符串。保持旧 prompt/context 逻辑，并自动注入对话记忆。
        额外参数：
          - session_id：会话隔离；同一个 session 会利用历史上下文
          - on_usage：回调，形如 lambda usage_dict: ...
        """
        context_str = _format_context_from_articles(
            articles,
            max_answer_tokens=800,
            max_question_tokens=60,
            model_for_token=self.model_name,
        )
        inputs = {"question": query, "context": context_str}

        usage_cb = UsageCallback(
            prompt_text_getter=lambda: _prompt_preview(self.prompt, inputs),
            model_name=self.model_name,
        )
        try:
            resp_text = self.chain_with_mem.invoke(
                inputs,
                config={
                    "configurable": {"session_id": session_id},
                    "callbacks": [usage_cb],
                },
            )
            return resp_text
        finally:
            if on_usage:
                on_usage(usage_cb.usage or {})

    # —— 方便测试/调试的历史操作 ——
    def get_history_messages(self, session_id: str):
        return self.history_store.get_history(session_id).messages

    def clear_history(self, session_id: str):
        self.history_store.get_history(session_id).clear()
