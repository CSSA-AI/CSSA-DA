from packages.rag_core.utils.article import Article
from abc import ABC, abstractmethod

class BaseGenerator(ABC):
    
    def __init__(self):
        pass

    @abstractmethod
    def generate(self, query: str, articles: list[Article]) -> str:
        pass