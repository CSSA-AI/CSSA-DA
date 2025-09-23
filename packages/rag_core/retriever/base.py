from packages.rag_core.utils.article import Article
from abc import ABC, abstractmethod
from typing import Tuple, List
class BaseRetriever(ABC):
    def __init__(self, input_list: List[Article]):
        self.articles = input_list
        pass
    
    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> List[Tuple[int, float, Article]]:
        pass
