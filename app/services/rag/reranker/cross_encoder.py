from .base import BaseReranker
from app.schemas.article import Article
from typing import List, Tuple
from sentence_transformers import CrossEncoder
from peft import PeftModel

class CrossEncoderReranker(BaseReranker):
    # model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L12-v2')

    def __init__(self, model, adapter_path=None):
        super().__init__()
        self.model = CrossEncoder(model)
        # 给底层 HF 模型加载 LoRA adapter
        if adapter_path:
            self.model.model = PeftModel.from_pretrained(self.model.model, adapter_path)

    def rerank(self, query, articles, top_k) -> List[Article]:
        if not articles:
            return []
        
        pairs = [(query, art[2].text) for art in articles]
        scores = self.model.predict(pairs)
        sorted_articles = sorted(zip(articles, scores), key=lambda x: x[1], reverse=True)
        return [art[0][2] for art in sorted_articles[:top_k]]
