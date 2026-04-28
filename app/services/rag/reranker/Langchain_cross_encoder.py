from .base import BaseReranker
from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from typing import List, Tuple, Dict, Any
from sentence_transformers import CrossEncoder
from peft import PeftModel

from langchain_core.runnables import RunnableLambda


class CrossEncoderReranker(BaseReranker):
    # model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L12-v2')

    def __init__(self, model_name, adapter_path=None):
        super().__init__()
        self.model = CrossEncoder(model_name)
        # 给底层 HF 模型加载 LoRA adapter
        if adapter_path:
            self.model.model = PeftModel.from_pretrained(self.model.model, adapter_path)

    def rerank(self, query, search_results: List[SearchResult], top_k: int = 3) -> List[SearchResult]:
        if not search_results:
            return []
        
        pairs = [(query, result.article.text) for result in search_results]
        scores = self.model.predict(pairs)

        for result, score in zip(search_results, scores):
            result.score = float(score)
        
        # 按新分数降序排序
        sorted_results = sorted(search_results, key=lambda x: x.score, reverse=True)
        
        # 4. 截取 Top K 并更新 Rank 字段 (可选，方便调试)
        final_results = sorted_results[:top_k]
        for rank, res in enumerate(final_results, start=1):
            res.rank = rank  # 标记最终排名，方便前端展示 "No.1 推荐"
            
        return final_results
    
    # LangChain Runnable 接口
    def _run(self, inputs: Dict[str, Any]) -> List[SearchResult]:
        """
        LCEL 会传入一个 dict，例如：
        {
            "query": "...",
            "search_results": [...]
        }
        """
        query = inputs["query"]
        search_results = inputs["search_results"]
        return self.rerank(query, search_results)

    def as_runnable(self):
        """
        返回一个 Runnable，可直接插入 LCEL pipeline。
        """
        return RunnableLambda(self._run)
