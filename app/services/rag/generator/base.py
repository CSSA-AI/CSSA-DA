# app/services/rag/generator/base.py

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, List, Optional, Dict, Any

from app.schemas.search_result import SearchResult


class BaseGenerator(ABC):
    """
    Generator core interface.

    Core generator 不需要依赖 LangChain。
    LangChain adapter 只需要调用 generate_text / stream_text。
    """

    @abstractmethod
    def generate_text(
        self,
        query: str,
        search_results: List[SearchResult],
        *,
        chat_history: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> str:
        """
        Non-streaming generation.
        """
        raise NotImplementedError

    def stream_text(
        self,
        query: str,
        search_results: List[SearchResult],
        *,
        chat_history: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Iterable[str]:
        """
        Streaming generation.

        默认 fallback：如果子类没有真正实现 streaming，
        就直接 yield 一整个非流式回答。
        """
        yield self.generate_text(
            query=query,
            search_results=search_results,
            chat_history=chat_history,
            **kwargs,
        )