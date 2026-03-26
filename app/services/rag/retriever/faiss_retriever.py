"""
LangChain 版本的 FAISS Retriever：
- 使用 LangChain 的 HuggingFaceEmbeddings + FAISS 向量库
- 仍然只用 Article.questions[0] 作为检索内容
- 对外仍然返回 List[SearchResult]，保持与原有接口兼容
"""

from __future__ import annotations
from typing import List, Tuple, Optional

import os
import json

from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.documents import Document

from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.retriever.base import BaseRetriever


class FAISSRetriever(BaseRetriever):
    """
    LangChain 化后的 FAISSRetriever：
    - 初始化时将 Article 列表转换为 LangChain Document 列表
    - 使用 HuggingFaceEmbeddings + FAISS 构建向量库
    - search() 返回 List[SearchResult]，与旧版保持兼容
    """

    def __init__(
        self,
        input_list: List[Article],
        model_name: str,
        *,
        embedding_model_name: Optional[str] = None,
    ):
        """
        :param input_list: Article 列表
        :param model_name: 逻辑上的“检索模型名”（保留给 BaseRetriever / 配置使用）
        :param embedding_model_name: 实际用于 HuggingFaceEmbeddings 的模型名
                                     若不指定，则默认使用 model_name
        """
        super().__init__(input_list, model_name)

        if not all(isinstance(x, Article) for x in input_list):
            raise TypeError("input_list must be a list of Article")

        if not model_name:
            raise ValueError("FAISSRetriever requires a model_name.")

        self.embedding_model_name = embedding_model_name or model_name

        # LangChain Embeddings
        self.embeddings = HuggingFaceEmbeddings(
            model_name=self.embedding_model_name,
        )

        # Article -> Document
        self._documents: List[Document] = self._build_documents_from_articles(self.articles)

        # LangChain FAISS VectorStore
        self._vectorstore: Optional[FAISS] = None
        self._retriever = None
        self._is_built = False

    # ---------- Article -> Document ----------

    def _article_to_doc(self, article: Article) -> Document:
        if not article.questions or not isinstance(article.questions, list):
            raise ValueError(f"Article {article.id} has no questions")

        question0 = article.questions[0]

        return Document(
            page_content=question0,
            metadata={
                "article": article  # ← 直接存整个 Article 对象
            }
        )

    def _build_documents_from_articles(self, articles: List[Article]) -> List[Document]:
        docs: List[Document] = []
        for a in articles:
            doc = self._article_to_doc(a)
            docs.append(doc)
        return docs

    # ---------- 构建 / 加载 向量库 ----------

    def _build_vectorstore(self):
        """
        使用 LangChain 的 FAISS.from_documents 构建向量库。
        """
        if not self._documents:
            raise RuntimeError("No documents to build FAISS index from.")

        self._vectorstore = FAISS.from_documents(
            self._documents,
            self.embeddings,
        )
        # 默认 retriever：相似度搜索，返回 top_k 文档
        self._retriever = self._vectorstore.as_retriever()
        self._is_built = True

    # ---------- 查询 ----------
    def search(self, query: str, top_k: int = 10) -> List[SearchResult]:
        if not self._is_built:
            self._build_vectorstore()

        # 兼容不同版本的 retriever API
        try:
            docs = self._retriever.get_relevant_documents(query)
        except AttributeError:
            docs = self._retriever.invoke(query)

        docs = docs[:top_k]

        results = []
        for rank, doc in enumerate(docs):
            article = doc.metadata["article"]  # ← 直接取出原始 Article

            # 你原来的 SearchResult 结构
            score = float(top_k - rank)
            results.append(SearchResult(article=article, score=score, rank=rank))

        return results


    # ---------- 保存 / 加载 ----------

    def save_all(self, dir_path: str):
        """
        使用 LangChain 的 save_local 保存向量库与相关信息。
        :param dir_path: 目录路径（而非单个文件）
        """
        if not self._is_built or self._vectorstore is None:
            # 如果还没 build，就先 build 一次
            self._build_vectorstore()

        os.makedirs(dir_path, exist_ok=True)

        # 1) 保存向量库（FAISS + embeddings）
        self._vectorstore.save_local(dir_path)

        # 2) 保存 Article 原始信息（用于恢复 Article 对象）
        articles_path = os.path.join(dir_path, "articles.json")
        with open(articles_path, "w", encoding="utf-8") as f:
            json.dump(
                [a.to_dict() for a in self.articles],
                f,
                ensure_ascii=False,
                indent=2,
            )

    def load_index(self, dir_path: str):
        """
        从本地目录加载向量库与 Article 信息。
        注意：这会覆盖当前的 self._vectorstore / self._retriever / self.articles。
        """
        # 1) 加载向量库
        self._vectorstore = FAISS.load_local(
            dir_path,
            self.embeddings,
            allow_dangerous_deserialization=True,  # 若你信任本地文件，可开启
        )
        self._retriever = self._vectorstore.as_retriever()
        self._is_built = True

        # 2) 加载 Article 列表
        articles_path = os.path.join(dir_path, "articles.json")
        if os.path.exists(articles_path):
            with open(articles_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.articles = [Article.from_dict(d) for d in data]
            # 重新构建 documents（保持一致性）
            self._documents = self._build_documents_from_articles(self.articles)
