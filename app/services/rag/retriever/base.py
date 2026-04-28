from abc import ABC, abstractmethod
from typing import List, Optional

from app.schemas.search_result import SearchResult


class BaseRetriever(ABC):
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name

    @abstractmethod
    def search(self, query: str, top_k: Optional[int] = None) -> List[SearchResult]:
        pass