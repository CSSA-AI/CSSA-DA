# python -m app.services.rag.tests.test_generator_eval
from app.schemas.article import Article
from app.schemas.search_result import SearchResult

from app.services.rag.generator.chatgpt_generator import ChatGPTGenerator
from app.services.rag.eval.generator_eval import GeneratorEvaluator

def build_mock_results():
    """
    构造一个模拟的检索结果列表，用于测试 generator。
    ground truth = gt-001
    """
    articles = [
        Article(
            text="你可以在PTV官网、便利店或火车站购买Myki卡。",
            questions=["如何办理Myki卡？"],
            id="gt-001",
            source="PTV",
            author="PTV",
            post_date="2024-01-01",
            created_at="2024-01-01T00:00:00",
            language="zh",
            tags=["myki", "ptv"],
            link="https://ptv.vic.gov.au"
        ),
        Article(
            text="墨尔本天气多变，与办理公交卡无关。",
            questions=["墨尔本天气如何？"],
            id="neg-001",
            source="BOM",
            author="BOM",
            post_date="2024-01-02",
            created_at="2024-01-02T00:00:00",
            language="zh",
            tags=["weather"],
            link="https://bom.gov.au"
        ),
        Article(
            text="维州公共交通包括火车、电车和公交车。",
            questions=["维州公共交通有哪些？"],
            id="neg-002",
            source="VIC GOV",
            author="VIC GOV",
            post_date="2024-01-03",
            created_at="2024-01-03T00:00:00",
            language="zh",
            tags=["transport"],
            link="https://vic.gov.au"
        )
    ]

    return [
        SearchResult(article=articles[0], score=0.9, rank=1),
        SearchResult(article=articles[1], score=0.5, rank=2),
        SearchResult(article=articles[2], score=0.4, rank=3)
    ]


def main():
    query = "在墨尔本如何办理公交卡？"
    ground_truth_ids = ["gt-001"]

    # 1. 初始化 ChatGPTGenerator（使用你的完整实现）
    generator = ChatGPTGenerator(model_name="gpt-5-nano", temperature=0.0)

    # 2. 构造模拟检索结果
    search_results = build_mock_results()

    # 3. 初始化 evaluator
    evaluator = GeneratorEvaluator()

    # 4. 运行评估
    metrics = evaluator.evaluate(
        query=query,
        search_results=search_results,
        ground_truth_ids=ground_truth_ids,
        generator=generator,
        session_id="test-session",
    )

    # 5. 打印结果
    print("\n===== Generator Evaluation =====")
    print("Answer:\n", metrics["answer"])
    print("\nRelevance:", metrics["relevance"])
    print("Groundedness:", metrics["groundedness"])
    print("Coverage:", metrics["coverage"])

if __name__ == "__main__":
    main()
