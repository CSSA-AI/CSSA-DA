from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from abc import ABC, abstractmethod
from typing import Tuple, List

class BaseReranker(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def rerank(self, query: str, search_results: List[SearchResult], top_k: int = 3) -> List[SearchResult]:
        pass
