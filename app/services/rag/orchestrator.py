import logging
from typing import Tuple, List

# 引入我们定好的标准契约
from app.schemas.search_result import SearchResult

from .retriever.base import BaseRetriever
from .reranker.base import BaseReranker
from .generator.base import BaseGenerator

logger = logging.getLogger(__name__)

class RAGOrchestrator:
    def __init__(self, retriever: BaseRetriever, reranker: BaseReranker, generator: BaseGenerator):
        self.retriever = retriever
        self.reranker = reranker
        self.generator = generator

    # [改动 1]: 返回值从 str 改为 Tuple[str, List]
    # 这样前端或者测试脚本就能知道："这句话是参考哪篇文章写的？"
    def run(self, query: str, session_id: str = "default") -> Tuple[str, List[SearchResult]]:
        logger.info(f"🚀 Starting RAG pipeline for query: {query}")
        
        # 1. Retrieve
        retrieve_result = self.retriever.search(query=query)
        logger.info(f"🔍 Retrieved {len(retrieve_result)} articles.")
        
        # 2. Rerank
        reranker_result = self.reranker.rerank(query=query, search_results=retrieve_result)
        logger.info(f"⚖️ Reranked and kept {len(reranker_result)} articles.")
        
        # 3. Generate (Blocking/Non-streaming)
        # [改动 2]: 传入 session_id，保证多轮对话正常
        generate_result = self.generator.generate_text(
            query=query, 
            search_results=reranker_result,
            session_id=session_id 
        )
        logger.info("🤖 Generated response successfully.")
        
        # 返回 (答案文本, 参考来源)
        return generate_result, reranker_result