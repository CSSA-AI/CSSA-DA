# app/services/rag/generator/chatgpt_generator.py

from __future__ import annotations

from typing import Iterable, List, Optional, Dict, Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from app.core.config import settings, rag_config
from app.schemas.search_result import SearchResult
from app.services.rag.generator.base import BaseGenerator
from app.services.rag.generator.context_formatter import (
    format_context_from_search_results,
)
from app.services.rag.errors import (
    GenerationTimeoutError,
    GenerationUnavailableError,
)


class ChatGPTGenerator(BaseGenerator):
    """
    LangChain-free generator core.

    职责：
    - query + search_results -> answer
    - 不负责 memory / tracing / orchestration
    """

    def __init__(
        self,
        *,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
        max_retries: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ):
        cfg = rag_config["generator"]

        api_key = api_key or settings.OPENAI_API_KEY
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for ChatGPTGenerator")

        self.model_name = model_name or cfg["model_name"]
        self.temperature = temperature if temperature is not None else cfg.get("temperature", 0.3)
        self.max_retries = (
            max_retries
            if max_retries is not None
            else cfg.get("max_retries", 2)
        )
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else cfg.get("timeout_seconds", 30.0)
        )
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        self.client = OpenAI(
            api_key=api_key,
            max_retries=self.max_retries,
            timeout=self.timeout_seconds,
        )

        self.streaming = cfg.get("streaming", False)

        self.system_prompt = cfg["system_prompt"]
        self.context_config = cfg.get("context", {})

    # ========= internal =========
    def _build_context(self, search_results: List[SearchResult]) -> str:
        return format_context_from_search_results(
            search_results,
            max_items=self.context_config.get("max_items", 5),
            max_chars_per_item=self.context_config.get("max_chars_per_item", 2000),
        )

    def _build_messages(
        self,
        query: str,
        context: str,
        chat_history: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, str]]:
        messages = []

        # system
        messages.append({
            "role": "system",
            "content": self.system_prompt,
        })

        # history（未来 adapter 可以传进来）
        if chat_history:
            messages.extend(chat_history)

        # user
        messages.append({
            "role": "user",
            "content": f"用户问题：{query}\n\n资料：\n{context}",
        })

        return messages

    # ========= non-stream =========
    def generate_text(
        self,
        query: str,
        search_results: List[SearchResult],
        *,
        chat_history: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> str:
        context = self._build_context(search_results)

        messages = self._build_messages(
            query=query,
            context=context,
            chat_history=chat_history,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=self.temperature,
            )
        except APITimeoutError as error:
            raise GenerationTimeoutError(
                "OpenAI generation timed out"
            ) from error
        except (
            APIConnectionError,
            InternalServerError,
            RateLimitError,
        ) as error:
            raise GenerationUnavailableError(
                "OpenAI generation is unavailable"
            ) from error

        return response.choices[0].message.content or ""

    # ========= streaming =========
    def stream_text(
        self,
        query: str,
        search_results: List[SearchResult],
        *,
        chat_history: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Iterable[str]:
        context = self._build_context(search_results)

        messages = self._build_messages(
            query=query,
            context=context,
            chat_history=chat_history,
        )

        try:
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=self.temperature,
                stream=True,
            )

            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except APITimeoutError as error:
            raise GenerationTimeoutError(
                "OpenAI generation timed out"
            ) from error
        except (
            APIConnectionError,
            InternalServerError,
            RateLimitError,
        ) as error:
            raise GenerationUnavailableError(
                "OpenAI generation is unavailable"
            ) from error
