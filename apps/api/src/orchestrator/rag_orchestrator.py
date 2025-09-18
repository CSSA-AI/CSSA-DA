from packages.rag_core.retriever.base import BaseRetriever
from packages.rag_core.reranker.base import BaseReranker
from packages.rag_core.generator.base import BaseGenerator

class RAGOrchestrator():
    def __init__(self, retriever: BaseRetriever, reranker: BaseReranker, generator: BaseGenerator):
        self.retriever = retriever
        self.reranker = reranker
        self.generator = generator

    def run(self, query: str):
        retrieve_result = self.retriever.search(query=query)
        print(f"Successfully retrieved {len(retrieve_result)} articles.")
        reranker_result = self.reranker.rerank(query=query, articles=retrieve_result)
        print(f"Successfully reranked and left {len(reranker_result)} articles.")
        generate_result = self.generator.generate(query = query, articles=reranker_result)
        print("Successfully generated response.")
        return generate_result
        

