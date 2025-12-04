from packages.rag_core.utils.article import Article
from abc import ABC, abstractmethod
from typing import Iterable

class BaseGenerator(ABC):
    
    def __init__(self):
        pass

    @abstractmethod
    def generate(self, query: str, articles: list[Article], **kwargs) -> Iterable[str]:
        """流式接口：yield 文本片段"""
        pass

    def generate_text(self, query: str, articles: list[Article], **kwargs) -> str:
        """一次性文本接口：在基于流式的情况下提供便利封装"""
        return "".join(self.generate(query, articles, **kwargs))