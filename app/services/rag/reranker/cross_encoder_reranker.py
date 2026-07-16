from typing import List, Optional
from sentence_transformers import CrossEncoder
from peft import PeftModel

from app.core.config import rag_config
from app.schemas.search_result import SearchResult
from app.services.rag.model_registry import model_registry
from .base import BaseReranker


class CrossEncoderReranker(BaseReranker):
    def __init__(
        self,
        model_name: Optional[str] = None,
        model_revision: Optional[str] = None,
        adapter_path: Optional[str] = None,
    ):
        reranker_config = rag_config["reranker"]

        uses_configured_model = (
            model_name is None
            and model_revision is None
            and adapter_path is None
        )
        if model_name is None:
            model_name = reranker_config["model_name"]
            model_revision = model_revision or reranker_config.get("model_revision")

        adapter_path = adapter_path or reranker_config.get("adapter_path")

        super().__init__()

        if uses_configured_model:
            self.model = model_registry.get_reranker_model()
        else:
            model_kwargs = {"revision": model_revision} if model_revision else {}
            self.model = CrossEncoder(model_name, **model_kwargs)

        # LoRA adapter（可选）
        if adapter_path and not uses_configured_model:
            self.model.model = PeftModel.from_pretrained(
                self.model.model,
                adapter_path
            )

    def rerank(
        self,
        query: str,
        search_results: List[SearchResult],
        top_k: Optional[int] = None,
    ) -> List[SearchResult]:

        if not search_results:
            return []

        top_k = top_k or rag_config["reranker"]["top_k"]

        pairs = [(query, result.article.text) for result in search_results]
        scores = self.model.predict(pairs)

        # ⚠️ 不直接改原对象（推荐）
        scored_results = []

        for result, score in zip(search_results, scores):
            new_result = SearchResult(
                article=result.article,
                score=float(score),
                rank=result.rank,  # 暂时保留
            )
            scored_results.append(new_result)

        # 排序
        sorted_results = sorted(
            scored_results,
            key=lambda x: x.score,
            reverse=True
        )

        # 截断 + 重新 rank
        final_results = sorted_results[:top_k]

        for rank, res in enumerate(final_results, start=1):
            res.rank = rank

        return final_results
