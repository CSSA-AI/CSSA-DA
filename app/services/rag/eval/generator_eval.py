from __future__ import annotations
from typing import List, Dict, Any
import re
import math

from app.schemas.search_result import SearchResult
from app.services.rag.generator.base import BaseGenerator

class GeneratorEvaluator:
    """
    评估生成器（LLM）的回答质量：
    - relevance：回答是否与 query + context 相关
    - groundedness：回答是否引用了 context（避免幻觉）
    - coverage：回答是否覆盖了 ground truth 文档的关键点
    """

    def __init__(self):
        pass

    # 1. Relevance（回答相关性）
    def relevance(self, answer: str, query: str) -> float:
        """
        简单但有效的相关性度量：
        - query 中的关键词是否出现在回答中
        """
        if not answer or not query:
            return 0.0

        q_tokens = set(re.findall(r"\w+", query.lower()))
        a_tokens = set(re.findall(r"\w+", answer.lower()))

        if not q_tokens:
            return 0.0

        overlap = len(q_tokens.intersection(a_tokens))
        return overlap / len(q_tokens)

    # 2. Groundedness（忠实性）
    def groundedness(self, answer: str, search_results: List[SearchResult]) -> float:
        """
        衡量回答是否基于检索到的文档：
        - answer 中的句子是否能在 context 中找到匹配片段
        """
        if not answer or not search_results:
            return 0.0

        context = "\n".join(r.article.text or "" for r in search_results).lower()
        answer_sents = [s.strip().lower() for s in re.split(r"[。.!?]", answer) if s.strip()]

        if not answer_sents:
            return 0.0

        hits = sum(1 for s in answer_sents if s[:20] in context)
        return hits / len(answer_sents)

    # 3. Coverage（覆盖率）
    def coverage(self, answer: str, ground_truth_ids: List[str], search_results: List[SearchResult]) -> float:
        """
        ground truth 文档中的关键点是否被回答覆盖。
        简化版：检查 ground truth 文档的标题/关键词是否出现在回答中。
        """
        if not answer or not ground_truth_ids:
            return 0.0

        answer = answer.lower()
        gt_articles = [
            r.article for r in search_results if r.article.id in ground_truth_ids
        ]

        if not gt_articles:
            return 0.0

        hits = 0
        for art in gt_articles:
            key = (art.title or "").lower()
            if key and key in answer:
                hits += 1

        return hits / len(gt_articles)

    # 4. 综合评估
    def evaluate(
        self,
        query: str,
        search_results: List[SearchResult],
        ground_truth_ids: List[str],
        generator: BaseGenerator,
        *,
        session_id: str = "eval",
    ) -> Dict[str, Any]:
        """
        统一评估接口：生成答案 + 计算三大指标。
        """
        answer = generator.generate_text(
            query,
            search_results,
            session_id=session_id,
        )

        return {
            "answer": answer,
            "relevance": self.relevance(answer, query),
            "groundedness": self.groundedness(answer, search_results),
            "coverage": self.coverage(answer, ground_truth_ids, search_results),
        }
