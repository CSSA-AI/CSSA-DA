import os
import time
from typing import List, Dict, Callable, Optional
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessageChunk
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.callbacks.manager import CallbackManagerForLLMRun

# ---------- 环境变量 ----------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found. Put it in your .env and keep .env out of Git.")

# ---------- 简单的会话内存存储（按 session_id 隔离） ----------
class InMemoryHistoryStore:
    def __init__(self):
        self._store: Dict[str, ChatMessageHistory] = {}

    def get_history(self, session_id: str) -> ChatMessageHistory:
        if session_id not in self._store:
            self._store[session_id] = ChatMessageHistory()
        return self._store[session_id]

# ---------- Token/耗时监测 ----------
class UsageCallback(BaseCallbackHandler):
    def __init__(self):
        self.started_at = None
        self.usage = {}

    def on_llm_start(self, *args, **kwargs):
        self.started_at = time.time()

    def on_llm_end(self, response, *, run_id, parent_run_id=None, **kwargs):
        elapsed = time.time() - (self.started_at or time.time())
        # 大多数 OpenAI 回包在 llm_output 里带 token 用量
        usage = {}
        try:
            usage = (response.llm_output or {}).get("token_usage", {})  # {'completion_tokens':..,'prompt_tokens':..,'total_tokens':..}
        except Exception:
            pass
        self.usage = {**usage, "elapsed_sec": round(elapsed, 3)}

    # 需要时你也可以在 on_llm_error 捕获异常

# ---------- 生成器模块 ----------
class GeneratorModule:
    """
    生成器：给定 query + context_docs，产出最终答案。
    支持：
      - 对话记忆（按 session_id）
      - 逐字流式输出（yield token）
      - API 调用监测（tokens、耗时）
    """
    def __init__(
        self,
        model_name: str = "gpt-5-nano",
        temperature: float = 0.3,
        max_retries: int = 2,
        history_store: Optional[InMemoryHistoryStore] = None,
    ):
        self.llm = ChatOpenAI(
            api_key=OPENAI_API_KEY,
            model=model_name,
            temperature=temperature,
            streaming=True,     # 开启底层流式
            max_retries=max_retries,
        )

        # Prompt：把历史对话放在 MessagesPlaceholder("chat_history")
        self.prompt = ChatPromptTemplate.from_messages([
            ("system",
             "你是CSSA智能助手，服务在澳洲的留学生。"
             "回答务必：准确、礼貌、精炼；如资料含来源/链接必须引用；"
             "若资料缺失就直说不知道，别编造；默认中文作答。"),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human",
             "用户问题：{question}\n\n"
             "资料（按编号给出，可能为空）：\n{context}\n\n"
             "请结合资料优先作答；如需引用，请在末尾以 [资料编号] 标注。")
        ])

        # LCEL：prompt → llm → 解析为字符串
        self.base_chain = self.prompt | self.llm | StrOutputParser()

        # 会话历史存储
        self.history_store = history_store or InMemoryHistoryStore()

        def _get_history(session_id: str) -> BaseChatMessageHistory:
            return self.history_store.get_history(session_id)

        # 把历史绑定到链上（输入的人类字段是 question；历史字段是 chat_history）
        self.chain = RunnableWithMessageHistory(
            self.base_chain,
            _get_history,
            input_messages_key="question",
            history_messages_key="chat_history",
        )

    # —— 将检索结果转成 Prompt 友好的块文本 ——
    @staticmethod
    def format_context(docs: List[Dict]) -> str:
        blocks = []
        for idx, d in enumerate(docs, 1):
            blocks.append(
                f"[资料{idx}] Q: {d.get('question','')}\n"
                f"A: {d.get('answer','')}\n"
                f"来源: {d.get('source','')}\n"
                f"链接: {d.get('link','')}\n"
                f"日期: {d.get('created_at','')}"
            )
        return "\n\n".join(blocks) if blocks else "(无可用资料)"

    # —— 一次性生成（非流式） ——
    def generate_answer(
        self,
        query: str,
        context_docs: List[Dict],
        session_id: str = "default",
        on_usage: Optional[Callable[[Dict], None]] = None,
    ) -> str:
        context_str = self.format_context(context_docs)
        usage_cb = UsageCallback()
        resp = self.chain.invoke(
            {"question": query, "context": context_str},
            config={"configurable": {"session_id": session_id}, "callbacks": [usage_cb]},
        )
        if on_usage:
            on_usage(usage_cb.usage)
        return resp

    # —— 逐字流式输出（yield token/文本增量） ——
    def stream_answer(
        self,
        query: str,
        context_docs: List[Dict],
        session_id: str = "default",
        on_usage: Optional[Callable[[Dict], None]] = None,
    ):
        context_str = self.format_context(context_docs)
        usage_cb = UsageCallback()

        # astream 返回的是异步生成器；这里用 sync 封装，便于直接 for 使用
        stream = self.chain.stream(
            {"question": query, "context": context_str},
            config={"configurable": {"session_id": session_id}, "callbacks": [usage_cb]},
        )

        full_text = []
        for chunk in stream:
            # chunk 是字符串（因为接了 StrOutputParser）；若没接解析器，也可能是 AIMessageChunk
            if isinstance(chunk, AIMessageChunk):
                piece = chunk.content or ""
            else:
                piece = str(chunk)
            full_text.append(piece)
            yield piece  # 把增量吐出去（前端可以逐字渲染）

        if on_usage:
            on_usage(usage_cb.usage)
        # 如需完整文本，也可以 return "".join(full_text)
