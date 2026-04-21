from typing import Any, Dict, List
from app.schemas.search_result import SearchResult
import math

class RetrieverEvaluator:
    """
    专门用于评估 Retriever 的质量。
    不依赖 reranker 或 generator，因此可以立即使用。
    """

    def __init__(self, k: int = 5):
        self.k = k

    # 1. Recall@k
    def recall_at_k(
        self,
        retrieved: List[SearchResult],
        ground_truth_ids: List[str]
    ) -> float:
        """
        retrieved: retriever.search() 的输出
        ground_truth_ids: 正确文档的 Article.id 列表
        """
        retrieved_ids = {r.article.id for r in retrieved[:self.k]}
        hit = len(retrieved_ids.intersection(ground_truth_ids))
        total = len(ground_truth_ids)
        return hit / total if total > 0 else 0.0

    # 2. Precision@k
    def precision_at_k(
        self,
        retrieved: List[SearchResult],
        ground_truth_ids: List[str]
    ) -> float:
        retrieved_ids = {r.article.id for r in retrieved[:self.k]}
        hit = len(retrieved_ids.intersection(ground_truth_ids))
        return hit / self.k

    # 3. nDCG@k
    def ndcg_at_k(
        self,
        retrieved: List[SearchResult],
        ground_truth_ids: List[str]
    ) -> float:
        """
        ground truth relevance: 相关文档 = 1，不相关 = 0
        """
        dcg = 0.0
        for i, r in enumerate(retrieved[:self.k]):
            rel = 1.0 if r.article.id in ground_truth_ids else 0.0
            dcg += rel / math.log2(i + 2)

        # 理想 DCG
        ideal_rels = [1.0] * min(len(ground_truth_ids), self.k)
        idcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ideal_rels))

        return dcg / idcg if idcg > 0 else 0.0

    # 4. Coverage
    def coverage(
        self,
        retrieved: List[SearchResult],
        ground_truth_ids: List[str]
    ) -> float:
        """
        ground truth 文档中有多少被召回（不限制 k）
        """
        retrieved_ids = {r.article.id for r in retrieved}
        hit = len(retrieved_ids.intersection(ground_truth_ids))
        total = len(ground_truth_ids)
        return hit / total if total > 0 else 0.0

    # 5. Error Analysis
    def error_analysis(
        self,
        retrieved: List[SearchResult],
        ground_truth_ids: List[str]
    ) -> Dict[str, Any]:
        retrieved_ids = [r.article.id for r in retrieved]

        return {
            "missing_ground_truth": [
                gid for gid in ground_truth_ids if gid not in retrieved_ids
            ],
            "false_positives": [
                rid for rid in retrieved_ids if rid not in ground_truth_ids
            ],
            "top_k_results": [
                {
                    "id": r.article.id,
                    "score": r.score,
                    "source": r.article.source,
                }
                for r in retrieved[:self.k]
            ]
        }
