from __future__ import annotations
from typing import List, Dict, Any
import re

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
        计算每个回答句子与 context 的词汇重叠率，取平均值。
        """
        if not answer or not search_results:
            return 0.0

        context_tokens = set(
            re.findall(r"\w+", "\n".join(r.article.text or "" for r in search_results).lower())
        )
        answer_sents = [s.strip() for s in re.split(r"[。.!?！？]", answer) if s.strip()]

        if not answer_sents:
            return 0.0

        total = 0.0
        for sent in answer_sents:
            tokens = re.findall(r"\w+", sent.lower())
            if not tokens:
                continue
            total += sum(1 for t in tokens if t in context_tokens) / len(tokens)

        return total / len(answer_sents)

    # 3. Coverage（覆盖率）
    def coverage(self, answer: str, ground_truth_ids: List[str], search_results: List[SearchResult]) -> float:
        """
        ground truth 文档中的关键点是否被回答覆盖。
        用文章的 GPT 生成问题（questions 字段）作为关键主题代理，
        计算回答与这些问题的词汇重叠率，取各 ground truth 文章的平均值。
        """
        if not answer or not ground_truth_ids:
            return 0.0

        answer_tokens = set(re.findall(r"\w+", answer.lower()))
        gt_articles = [
            r.article for r in search_results if r.article.id in ground_truth_ids
        ]

        if not gt_articles:
            return 0.0

        scores = []
        for art in gt_articles:
            key_content = " ".join(art.questions) if art.questions else (art.text or "")[:500]
            key_tokens = set(re.findall(r"\w+", key_content.lower()))
            if not key_tokens:
                scores.append(0.0)
                continue
            scores.append(len(answer_tokens & key_tokens) / len(key_tokens))

        return sum(scores) / len(scores)

    # 4. 综合评估
    def evaluate(
        self,
        query: str,
        search_results: List[SearchResult],
        ground_truth_ids: List[str],
        generator: BaseGenerator,
    ) -> Dict[str, Any]:
        """
        统一评估接口：生成答案 + 计算三大指标。
        """
        answer = generator.generate_text(query, search_results)

        return {
            "answer": answer,
            "relevance": self.relevance(answer, query),
            "groundedness": self.groundedness(answer, search_results),
            "coverage": self.coverage(answer, ground_truth_ids, search_results),
        }
