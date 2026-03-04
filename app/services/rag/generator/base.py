from abc import ABC, abstractmethod
from typing import Iterable, List, Optional, Callable, Dict

# 关键修改 1: 引入标准契约 SearchResult
from app.schemas.search_result import SearchResult

class BaseGenerator(ABC):
    
    def __init__(self):
        pass

    @abstractmethod
    def generate(
        self, 
        query: str, 
        search_results: List[SearchResult],  # 关键修改 2: 输入变成 SearchResult 列表
        *,
        session_id: str = "default",        # 关键修改 3: 显式定义 session_id (不要藏在 kwargs 里)
        on_usage: Optional[Callable[[Dict], None]] = None, # 关键修改 4: 显式定义回调，方便统计 Token
        **kwargs
    ) -> Iterable[str]:
        """
        流式接口：yield 文本片段。
        必须支持 session_id 以利用对话历史。
        """
        pass

    def generate_text(
        self, 
        query: str, 
        search_results: List[SearchResult], 
        *,
        session_id: str = "default",
        on_usage: Optional[Callable[[Dict], None]] = None,
        **kwargs
    ) -> str:
        """
        一次性文本接口：在基于流式的情况下提供便利封装。
        注意：这里也要透传 session_id 和 on_usage。
        """
        # 将参数透传给 generate
        return "".join(
            self.generate(
                query, 
                search_results, 
                session_id=session_id, 
                on_usage=on_usage, 
                **kwargs
            )
        )