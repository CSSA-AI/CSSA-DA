from __future__ import annotations
from typing import Any, Dict, List

from app.schemas.search_result import SearchResult
from app.services.rag.retriever.base import BaseRetriever
from app.services.rag.reranker.base import BaseReranker
from app.services.rag.generator.base import BaseGenerator
from app.services.rag.eval.retriever_eval import RetrieverEvaluator
from app.services.rag.eval.reranker_eval import RerankerEvaluator
from app.services.rag.eval.generator_eval import GeneratorEvaluator


class PipelineEvaluator:
    """
    端到端 RAG pipeline 评估器：retriever → reranker → generator 各阶段指标 + 整体汇总。

    用法::

        evaluator = PipelineEvaluator(retriever, reranker, generator)

        # 单条
        result = evaluator.evaluate(query, ground_truth_ids)

        # 批量
        report = evaluator.evaluate_batch(
            [{"query": "...", "ground_truth_ids": ["id1", "id2"]}, ...]
        )
        print(report["aggregate"])
    """

    _RETRIEVER_SCALAR_KEYS = ("recall@k", "precision@k", "ndcg@k", "coverage")
    _GENERATOR_SCALAR_KEYS = ("relevance", "groundedness", "coverage")

    def __init__(
        self,
        retriever: BaseRetriever,
        reranker: BaseReranker,
        generator: BaseGenerator,
        retriever_k: int = 5,
        reranker_k: int = 3,
    ):
        self.retriever = retriever
        self.reranker = reranker
        self.generator = generator
        self._ret_eval = RetrieverEvaluator(k=retriever_k)
        self._rer_eval = RerankerEvaluator(k=reranker_k)
        self._gen_eval = GeneratorEvaluator()

    def evaluate(
        self,
        query: str,
        ground_truth_ids: List[str],
        *,
        session_id: str = "eval",
    ) -> Dict[str, Any]:
        """
        对单条 query 跑完整 pipeline，返回各阶段指标。

        返回结构::

            {
              "query": str,
              "retriever": { "recall@k", "precision@k", "ndcg@k", "coverage", "error_analysis" },
              "reranker":  { "recall@k", "precision@k", "ndcg@k", "coverage", "error_analysis" },
              "generator": { "answer", "relevance", "groundedness", "coverage" },
            }
        """
        # Stage 1: Retrieve
        retrieved: List[SearchResult] = self.retriever.search(query)
        retriever_metrics: Dict[str, Any] = {
            "recall@k":       self._ret_eval.recall_at_k(retrieved, ground_truth_ids),
            "precision@k":    self._ret_eval.precision_at_k(retrieved, ground_truth_ids),
            "ndcg@k":         self._ret_eval.ndcg_at_k(retrieved, ground_truth_ids),
            "coverage":       self._ret_eval.coverage(retrieved, ground_truth_ids),
            "error_analysis": self._ret_eval.error_analysis(retrieved, ground_truth_ids),
        }

        # Stage 2: Rerank
        reranked: List[SearchResult] = self.reranker.rerank(query, retrieved)
        reranker_metrics: Dict[str, Any] = {
            "recall@k":       self._rer_eval.recall_at_k(reranked, ground_truth_ids),
            "precision@k":    self._rer_eval.precision_at_k(reranked, ground_truth_ids),
            "ndcg@k":         self._rer_eval.ndcg_at_k(reranked, ground_truth_ids),
            "coverage":       self._rer_eval.coverage(reranked, ground_truth_ids),
            "error_analysis": self._rer_eval.error_analysis(reranked, ground_truth_ids),
        }

        # Stage 3: Generate + evaluate
        generator_metrics: Dict[str, Any] = self._gen_eval.evaluate(
            query, reranked, ground_truth_ids, self.generator, session_id=session_id
        )

        return {
            "query": query,
            "retriever": retriever_metrics,
            "reranker": reranker_metrics,
            "generator": generator_metrics,
        }

    def evaluate_batch(
        self,
        test_cases: List[Dict[str, Any]],
        *,
        session_id: str = "eval",
    ) -> Dict[str, Any]:
        """
        批量评估，返回逐条结果 + 数值指标的宏平均。

        test_cases 格式::

            [{"query": str, "ground_truth_ids": List[str]}, ...]

        返回结构::

            {
              "per_query": [ <evaluate() 的输出>, ... ],
              "aggregate": {
                "retriever": { "recall@k", "precision@k", "ndcg@k", "coverage" },
                "reranker":  { "recall@k", "precision@k", "ndcg@k", "coverage" },
                "generator": { "relevance", "groundedness", "coverage" },
              }
            }
        """
        per_query: List[Dict[str, Any]] = [
            self.evaluate(case["query"], case["ground_truth_ids"], session_id=session_id)
            for case in test_cases
        ]
        return {"per_query": per_query, "aggregate": self._aggregate(per_query)}

    # ------------------------------------------------------------------ #

    def _aggregate(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """各数值指标跨 query 取宏平均。"""
        n = len(results)
        if n == 0:
            return {}

        def mean(stage: str, key: str) -> float:
            return sum(r[stage][key] for r in results) / n

        return {
            "retriever": {k: mean("retriever", k) for k in self._RETRIEVER_SCALAR_KEYS},
            "reranker":  {k: mean("reranker",  k) for k in self._RETRIEVER_SCALAR_KEYS},
            "generator": {k: mean("generator", k) for k in self._GENERATOR_SCALAR_KEYS},
        }
