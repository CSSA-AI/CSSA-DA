from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.schemas.chat import ChatRequest, ChatResponse

article = Article(
    text="租房可以通过 Flatmates 和 Facebook 群组找房源",
    questions=["如何租房？", "怎么找房？"],
    source="生活专区",
    tags=["住宿", "租房"]
)

result = SearchResult(
    article=article,
    score=0.95,
    rank=1
)

response = ChatResponse(
    query="如何租房？",
    answer="你可以通过 Flatmates 和 Facebook 群组寻找房源。",
    results=[result]
)

print(response.model_dump())