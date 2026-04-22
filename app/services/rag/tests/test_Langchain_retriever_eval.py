# python -m app.services.rag.tests.test_retriever_eval
from app.schemas.article import Article
from app.services.rag.retriever.Langchain_faiss_retriever import FAISSRetriever
from app.services.rag.eval.retriever_eval import RetrieverEvaluator

# -----------------------------
# 1. 构造一些测试 Article
# -----------------------------
articles = [
    Article(text="苹果是一种水果", questions=["苹果是什么？"]),
    Article(text="香蕉是黄色的水果", questions=["香蕉是什么？"]),
    Article(text="猫是哺乳动物", questions=["猫是什么？"]),
]

# -----------------------------
# 2. 初始化 Retriever
# -----------------------------
retriever = FAISSRetriever(
    input_list=articles,
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

# -----------------------------
# 3. 运行检索
# -----------------------------
query = "苹果是什么？"
retrieved = retriever.search(query, top_k=3)

# 假设 ground truth 是第一篇文章
ground_truth_ids = [articles[0].id]

# -----------------------------
# 4. 初始化 Evaluator
# -----------------------------
evaluator = RetrieverEvaluator(k=3)

print("Recall@3:", evaluator.recall_at_k(retrieved, ground_truth_ids))
print("Precision@3:", evaluator.precision_at_k(retrieved, ground_truth_ids))
print("nDCG@3:", evaluator.ndcg_at_k(retrieved, ground_truth_ids))
print("Coverage:", evaluator.coverage(retrieved, ground_truth_ids))
print("Error Analysis:", evaluator.error_analysis(retrieved, ground_truth_ids))
