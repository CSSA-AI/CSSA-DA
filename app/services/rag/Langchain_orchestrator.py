from typing import Dict, Any
from langchain_core.runnables import RunnableLambda, RunnableMap, RunnableParallel


class LCRAGOrchestrator:
    def __init__(self, retriever, reranker, generator):
        self.retriever = retriever
        self.reranker = reranker
        self.generator = generator

        # 1. retriever runnable
        self.retriever_node = RunnableLambda(
            lambda query: self.retriever.search(query)
        )

        # 2. reranker runnable（你已经实现 as_runnable）
        self.reranker_node = self.reranker.as_runnable()

        # 3. generator runnable（ChatGPTGenerator 已经是 Runnable）
        self.generator_node = self.generator.as_runnable()

        # 4. 构建 LCEL pipeline
        self.chain = (
            # Step 1: 保证输入是 dict
            RunnableMap({
                "query": lambda x: x["query"]
            })
            # Step 2: retriever
            | RunnableMap({
                "query": lambda x: x["query"],
                "search_results": lambda x: self.retriever_node.invoke(x["query"])
            })
            # Step 3: reranker
            | RunnableMap({
                "query": lambda x: x["query"],
                "reranked_results": lambda x: self.reranker_node.invoke({
                    "query": x["query"],
                    "search_results": x["search_results"]
                })
            })
            # Step 4: generator
            | RunnableLambda(lambda x: self.generator_node.invoke({
                "query": x["query"],
                "reranked_results": x["reranked_results"]
            }))
        )

    def as_runnable(self):
        return self.chain

    def run(self, query: str) -> Dict[str, Any]:
        """
        保留一个兼容旧接口的 run() 方法
        """
        return self.chain.invoke({"query": query})
