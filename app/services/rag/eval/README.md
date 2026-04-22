# 📊 RAG Evaluation Module

本目录包含对 RAG 系统各模块的评估工具，包括检索器、重排序器与生成器的质量评估。

eval/
│
├── init.py
├── evaluator.py         # 主评估器（可组合多种指标）
│
├── retriever_eval.py    # 专门评估 Retriever
├── reranker_eval.py     # 专门评估 Reranker
└── generator_eval.py    # 专门评估 Generator

---

## 🔍 Retriever Evaluation

用于评估检索器（Retriever）的召回能力、排序质量与覆盖率。

### 支持指标

- **recall@k**  
  前 k 条结果中命中的正确文档比例。

- **precision@k**  
  前 k 条结果中真正相关文档的比例。

- **ndcg@k**  
  排序质量指标，衡量相关文档是否被排在更靠前的位置。

- **coverage**  
  在所有检索结果中命中的 ground truth 文档比例（不限 k）。

- **error analysis**  
  展示：
  - 哪些正确文档被漏掉  
  - 哪些错误文档被返回  
  - 前 k 条结果的详细排序情况  

---

## ⚖️ Reranker Evaluation

用于评估重排序器（Reranker）是否提升了排序质量。

- 复用 retriever 的指标（recall@k、ndcg@k 等）
- 对比 rerank 前后的排序差异
- 分析 reranker 是否将正确文档提升到更靠前位置

---

## 🧠 Generator Evaluation

用于评估生成器（Generator）的回答质量。

### 支持指标

- **Answer Relevance**  
  回答是否真正利用了检索到的 SearchResult 内容。

- **Faithfulness**  
  回答是否忠实于检索内容，是否存在 hallucination。

- **Context Coverage**  
  回答是否覆盖了 ground truth 文档中的关键点。

---
