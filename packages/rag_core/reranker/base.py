from packages.rag_core.utils.article import Article
from abc import ABC, abstractmethod
from typing import Tuple, List

class BaseReranker(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def rerank(self, query: str, articles: List[Tuple[int, float, Article]], top_k: int = 3) -> List[Article]:
        pass
