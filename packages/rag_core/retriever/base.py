from packages.rag_core.utils.article import Article
from abc import ABC, abstractmethod
from typing import Tuple, List
class BaseRetriever(ABC):
    def __init__(self, input_list: List[Article], model_name: str = None):
        self.articles = input_list
        self.model_name = model_name
        pass
    
    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> List[Tuple[int, float, Article]]:
        pass
