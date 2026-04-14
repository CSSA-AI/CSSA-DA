from fastapi import APIRouter
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.rag.factory import init_rag_system

router = APIRouter()

# ⭐ 初始化一次（关键）
rag_orchestrator = init_rag_system()


@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    # 调用已经写好的 orchestrator
    answer, results = rag_orchestrator.run(
        query=request.query,
        session_id="default"
    )

    return ChatResponse(
        query=request.query,
        answer=answer,
        results=results
    )