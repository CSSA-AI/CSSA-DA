from typing import List, Dict, Any
import math

from app.schemas.search_result import SearchResult
from app.services.rag.reranker.base import BaseReranker

class RerankerEvaluator:
    def __init__(self, k: int = 3):
        self.k = k

    def recall_at_k(
        self,
        reranked_results: List[SearchResult],
        ground_truth_ids: List[str],
        k: int | None = None,
    ) -> float:
        if not ground_truth_ids:
            return 0.0

        k = k or self.k
        top_k = reranked_results[:k]
        hit_ids = {r.article.id for r in top_k if r.article and r.article.id in ground_truth_ids}
        return len(hit_ids) / len(set(ground_truth_ids))

    def precision_at_k(
        self,
        reranked_results: List[SearchResult],
        ground_truth_ids: List[str],
        k: int | None = None,
    ) -> float:
        k = k or self.k
        if k == 0:
            return 0.0

        top_k = reranked_results[:k]
        hit_count = sum(
            1 for r in top_k if r.article and r.article.id in ground_truth_ids
        )
        return hit_count / k

    def _dcg(self, relevances: List[int]) -> float:
        dcg = 0.0
        for i, rel in enumerate(relevances, start=1):
            if rel > 0:
                dcg += (2**rel - 1) / math.log2(i + 1)
        return dcg

    def ndcg_at_k(
        self,
        reranked_results: List[SearchResult],
        ground_truth_ids: List[str],
        k: int | None = None,
    ) -> float:
        k = k or self.k
        if not ground_truth_ids:
            return 0.0

        top_k = reranked_results[:k]
        relevances = [
            1 if r.article and r.article.id in ground_truth_ids else 0
            for r in top_k
        ]

        dcg = self._dcg(relevances)
        # IDCG must reflect the true number of relevant docs, not just those in top_k
        n_relevant = min(len(ground_truth_ids), k)
        ideal_relevances = [1] * n_relevant + [0] * (k - n_relevant)
        idcg = self._dcg(ideal_relevances)

        if idcg == 0:
            return 0.0
        return dcg / idcg

    def coverage(
        self,
        reranked_results: List[SearchResult],
        ground_truth_ids: List[str],
    ) -> float:
        if not ground_truth_ids:
            return 0.0

        retrieved_ids = {r.article.id for r in reranked_results if r.article}
        hit_ids = retrieved_ids.intersection(set(ground_truth_ids))
        return len(hit_ids) / len(set(ground_truth_ids))

    def error_analysis(
        self,
        reranked_results: List[SearchResult],
        ground_truth_ids: List[str],
        k: int | None = None,
    ) -> Dict[str, Any]:
        k = k or self.k
        top_k = reranked_results[:k]

        retrieved_ids = [r.article.id for r in top_k if r.article]
        gt_set = set(ground_truth_ids)

        missing_ground_truth = list(gt_set.difference(retrieved_ids))
        false_positives = [rid for rid in retrieved_ids if rid not in gt_set]

        top_k_results = [
            {
                "id": r.article.id if r.article else None,
                "score": r.score,
                "rank": getattr(r, "rank", None),
            }
            for r in top_k
        ]

        return {
            "missing_ground_truth": missing_ground_truth,
            "false_positives": false_positives,
            "top_k_results": top_k_results,
        }

    def evaluate(
        self,
        query: str,
        search_results: List[SearchResult],
        ground_truth_ids: List[str],
        reranker: BaseReranker,
        k: int | None = None,
    ) -> Dict[str, Any]:
        """
        一次性跑 rerank + 各种指标，方便在 test 脚本里调用。
        """
        k = k or self.k
        reranked = reranker.rerank(query, search_results, top_k=k)

        return {
            "recall@k": self.recall_at_k(reranked, ground_truth_ids, k),
            "precision@k": self.precision_at_k(reranked, ground_truth_ids, k),
            "ndcg@k": self.ndcg_at_k(reranked, ground_truth_ids, k),
            "coverage": self.coverage(reranked, ground_truth_ids),
            "error_analysis": self.error_analysis(reranked, ground_truth_ids, k),
        }
