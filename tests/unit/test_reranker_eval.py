# python -m app.services.rag.tests.test_reranker_eval
from app.schemas.article import Article
from app.schemas.search_result import SearchResult

from app.services.rag.reranker.cross_encoder import CrossEncoderReranker
from app.services.rag.eval.reranker_eval import RerankerEvaluator

def build_mock_results():
    """
    构造一个模拟的检索结果列表，用于测试 reranker。
    其中只有一篇是 ground truth。
    """
    articles = [
        Article(id="gt-001", title="正确文档", text="这是正确答案的内容。"),
        Article(id="neg-001", title="干扰文档1", text="这是不相关的内容 AAA"),
        Article(id="neg-002", title="干扰文档2", text="这是不相关的内容 BBB"),
    ]

    # 模拟初始检索结果（顺序是乱的）
    results = [
        SearchResult(article=articles[1], score=0.5, rank=1),
        SearchResult(article=articles[2], score=0.4, rank=2),
        SearchResult(article=articles[0], score=0.3, rank=3),  # 正确文档排在最后
    ]

    return results

def main():
    query = "正确答案是什么？"
    ground_truth_ids = ["gt-001"]

    # 1. 初始化 CrossEncoder reranker
    model_name = "cross-encoder/ms-marco-MiniLM-L12-v2"
    reranker = CrossEncoderReranker(model_name)
    # reranker = CrossEncoderReranker(model_name, adapter_path="lora_adapter/")

    # 2. 构造模拟检索结果
    search_results = build_mock_results()

    # 3. 初始化 evaluator
    evaluator = RerankerEvaluator(k=3)

    # 4. 运行评估
    metrics = evaluator.evaluate(
        query=query,
        search_results=search_results,
        ground_truth_ids=ground_truth_ids,
        reranker=reranker,
        top_k=3
    )

    # 5. 打印结果
    print("\n===== Reranker Evaluation =====")
    for key, value in metrics.items():
        print(f"{key}: {value}")

if __name__ == "__main__":
    main()
