import json
import os

from app.schemas.article import Article
from app.services.rag.orchestrator import RAGOrchestrator
from app.services.rag.retriever.faiss_retriever import FAISSRetriever
from app.services.rag.reranker.cross_encoder import CrossEncoderReranker
from app.services.rag.generator.chatgpt_generator import ChatGPTGenerator


def init_rag_system() -> RAGOrchestrator:
    DATA_PATH = "data/demo_data.json"

    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(f"Data file not found: {DATA_PATH}")

    # 1. 读取数据
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # 2. 转成 Article 对象
    all_articles = [Article(**item) for item in raw_data]

    # 3. 初始化三大组件
    retriever = FAISSRetriever(
        input_list=all_articles,
        model_name="BAAI/bge-m3"
    )

    reranker = CrossEncoderReranker(
        model_name="BAAI/bge-reranker-v2-m3"
    )

    generator = ChatGPTGenerator(
        model_name="gpt-4o-mini"
    )

    # 4. 组装 orchestrator
    orchestrator = RAGOrchestrator(
        retriever=retriever,
        reranker=reranker,
        generator=generator
    )

    return orchestrator