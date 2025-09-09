from packages.rag_core.utils.article import Article
from abc import ABC, abstractmethod

class BaseReranker(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def rerank(self, query: str, articles: list[set[int, float, Article]]) -> list[Article]:
        pass
