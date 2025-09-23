# -*- coding: utf-8 -*-
# packages/rag_core/generator/chatgpt_generator.py

from __future__ import annotations
from typing import List, Dict, Optional, Callable
import os
import time

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
if not OPENAI_API_KEY:
    # 这里不抛错，便于某些测试场景；也可以改成 raise ValueError(...)
    pass


# ========== 用量监测回调 ==========
class UsageCallback(BaseCallbackHandler):
    """统计本次调用的 tokens 与耗时；回传给上层 on_usage 回调。"""
    def __init__(self):
        self._started_at = None
        self.usage: Dict = {}

    def on_llm_start(self, *args, **kwargs):
        self._started_at = time.time()

    def on_llm_end(self, response, **kwargs):
        elapsed = time.time() - (self._started_at or time.time())
        usage = {}
        try:
            # 兼容不同 SDK 回包结构
            usage = (response.llm_output or {}).get("token_usage", {})
        except Exception:
            pass
        self.usage = {**usage, "elapsed_sec": round(elapsed, 3)}


# ========== 简单的会话历史存储（按 session_id 隔离） ==========
class InMemoryHistoryStore:
    def __init__(self):
        self._store: Dict[str, ChatMessageHistory] = {}

    def get_history(self, session_id: str) -> ChatMessageHistory:
        if session_id not in self._store:
            self._store[session_id] = ChatMessageHistory()
        return self._store[session_id]


# ========== 工具函数：保持原来的 context 格式 ==========
def _format_context_from_articles(
    articles: List[Article],
    *,
    max_answer_len: int = 800,   # 防止上下文过长，按需调整
    max_question_len: int = 200
) -> str:
    """
    将 Article 列表格式化为给 LLM 的上下文字符串，保持 Q/A/来源/链接/日期 的样式。
    - Q:  questions[0] -> title
    - A:  text -> raw_text -> summary()
    - 来源: source -> author
    - 日期: created_at -> post_date
    - 链接: link
    会做 None 防护与长度截断。
    """
    if not articles:
        return ""

    def _norm(s: str | None) -> str:
        """把 None -> ''，并做简单空白清理。"""
        if not s:
            return ""
        # 统一空白，去掉两端空格
        return " ".join(str(s).split()).strip()

    blocks: list[str] = []

    for art in articles:
        # Q
        q = None
        if isinstance(art.questions, list) and art.questions:
            q = art.questions[0]
        q = _norm(q or art.title)
        if q and len(q) > max_question_len:
            q = q[:max_question_len] + "..."

        # A
        atext = _norm(art.text) or _norm(art.raw_text)
        if not atext:
            # 用 summary()（其内部会在 text 为 None 时出错，所以要兜底）
            try:
                atext = _norm(art.summary(length=max_answer_len))
            except Exception:
                atext = ""
        if atext and len(atext) > max_answer_len:
            atext = atext[:max_answer_len] + "..."

        # 其它字段
        source = _norm(art.source) or _norm(art.author)
        link = _norm(art.link)
        date = _norm(art.created_at) or _norm(art.post_date)

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
        # 底层 LLM
        self.llm = ChatOpenAI(
            api_key=OPENAI_API_KEY,
            model=model_name,
            temperature=temperature,
            streaming=True,      # 允许底层流式（便于后续扩展 stream_generate）
            max_retries=max_retries,
        )

        # —— 保持原有 Prompt 内容，但改成 ChatPromptTemplate + MessagesPlaceholder 以承载记忆 ——
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

        # —— 会话历史仓库（按 session_id 区分） ——
        self.history_store = history_store or InMemoryHistoryStore()

        def _get_history(session_id: str) -> BaseChatMessageHistory:
            return self.history_store.get_history(session_id)

        # —— 绑定记忆：把 chat_history 注入到 MessagesPlaceholder 中 ——
        self.chain_with_mem = RunnableWithMessageHistory(
            self.base_chain,
            _get_history,
            input_messages_key="question",      # 只把 question 当成“人类输入”写入历史
            history_messages_key="chat_history" # 历史插槽
        )

    # base.py 的要求：generate(self, query: str, articles: list[Article]) -> str
    def generate(
        self,
        query: str,
        articles: List[Article],
        *,
        session_id: str = "default",
        on_usage: Optional[Callable[[Dict], None]] = None,
    ):
        """
        逐字/逐块流式生成。yield 出文本增量；末尾触发 on_usage。
        """
        context_str = _format_context_from_articles(articles)
        inputs = {"question": query, "context": context_str}

        usage_cb = UsageCallback()
        stream = self.chain_with_mem.stream(
            inputs,
            config={
                "configurable": {"session_id": session_id},
                "callbacks": [usage_cb],
            },
        )
        full = []
        for piece in stream:
            full.append(piece)
            yield piece

        if on_usage:
            on_usage(usage_cb.usage)
    

    # 可选：如果后续需要“返回一次性完整答案字符串输出”，可以用这个接口：
    def generate2(
        self,
        query: str,
        articles: List[Article],
        *,
        session_id: str = "default",
        on_usage: Optional[Callable[[Dict], None]] = None,
    ) -> str:
        """
        返回一次性完整答案字符串。保持旧 prompt/context 逻辑，并自动注入对话记忆。
        额外参数：
          - session_id：会话隔离；同一个 session 会利用历史上下文
          - on_usage：回调，形如 lambda usage_dict: ...
        """
        context_str = _format_context_from_articles(articles)
        inputs = {"question": query, "context": context_str}

        usage_cb = UsageCallback()
        resp_text = self.chain_with_mem.invoke(
            inputs,
            config={
                "configurable": {"session_id": session_id},
                "callbacks": [usage_cb],
            },
        )

        if on_usage:
            on_usage(usage_cb.usage)

        return resp_text


    # —— 方便测试/调试的历史操作 ——
    def get_history_messages(self, session_id: str):
        return self.history_store.get_history(session_id).messages

    def clear_history(self, session_id: str):
        self.history_store.get_history(session_id).clear()
