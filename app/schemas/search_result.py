from pydantic import BaseModel
from app.schemas.article import Article
from typing import Optional

class SearchResult(BaseModel):
    """
    这是 Retriever 和 Reranker 的规范输出格式。
    """
    article: Article
    score: float
    rank: Optional[int] = None  # 排名