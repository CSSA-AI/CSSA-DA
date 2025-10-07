from .base import BaseReranker
from packages.rag_core.utils.article import Article
from typing import List, Tuple
from sentence_transformers import CrossEncoder

class CrossEncoderReranker(BaseReranker):
    model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L12-v2')

    def __init__(self, model):
        super().__init__()
        self.model = CrossEncoder(model)

    def rerank(self, query, articles, top_k) -> List[Article]:
        if not articles:
            return []
        
        pairs = [(query, art[2].raw_text) for art in articles]
        scores = self.model.predict(pairs)
        sorted_articles = sorted(zip(articles, scores), key=lambda x: x[1], reverse=True)
        return [art[0][2] for art in sorted_articles[:top_k]]
