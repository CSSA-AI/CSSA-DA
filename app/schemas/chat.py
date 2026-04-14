from typing import List
from pydantic import BaseModel, Field
from app.schemas.search_result import SearchResult


class ChatRequest(BaseModel):
    """
    前端发送给聊天接口的请求体
    """
    query: str = Field(..., description="用户输入的问题")


class ChatResponse(BaseModel):
    """
    聊天接口返回给前端的响应体
    """
    query: str
    answer: str
    results: List[SearchResult] = Field(default_factory=list)