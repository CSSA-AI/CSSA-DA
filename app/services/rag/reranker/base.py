from abc import ABC, abstractmethod
from typing import List, Optional

from app.schemas.search_result import SearchResult

class BaseReranker(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def rerank(
        self,
        query: str,
        search_results: List[SearchResult],
        top_k: Optional[int] = None,
    ) -> List[SearchResult]:
        pass
