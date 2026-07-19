from contextlib import asynccontextmanager
import logging
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Request, status as http_status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.deps import (
    close_rag_orchestrator,
    get_rag_orchestrator,
    require_internal_api_key,
)
from app.core.config import settings
from app.core.logging import configure_app_logging
from app.schemas.search_result import SearchResult
from app.services.readiness import check_readiness
from app.services.system_status import get_system_status
from app.services.rag.orchestrator import RAGOrchestrator
from app.services.rag.errors import (
    GenerationTimeoutError,
    GenerationUnavailableError,
    RAGServiceError,
    RetrievalUnavailableError,
)


configure_app_logging(settings.LOG_LEVEL)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    close_rag_orchestrator()


app = FastAPI(
    title="CSSA-DA RAG API",
    version="0.1.0",
    description="RAG chatbot API for Chinese students and scholars in Australia.",
    lifespan=lifespan,
)


def _service_error_response(
    error: RAGServiceError,
    status_code: int,
) -> JSONResponse:
    logger.error(
        "RAG request failed: %s",
        error,
        exc_info=(type(error), error, error.__traceback__),
    )
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": error.code,
                "message": error.public_message,
            }
        },
    )


@app.exception_handler(RetrievalUnavailableError)
def handle_retrieval_unavailable(
    _: Request,
    error: RetrievalUnavailableError,
) -> JSONResponse:
    return _service_error_response(
        error,
        http_status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@app.exception_handler(GenerationUnavailableError)
def handle_generation_unavailable(
    _: Request,
    error: GenerationUnavailableError,
) -> JSONResponse:
    return _service_error_response(
        error,
        http_status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@app.exception_handler(GenerationTimeoutError)
def handle_generation_timeout(
    _: Request,
    error: GenerationTimeoutError,
) -> JSONResponse:
    return _service_error_response(
        error,
        http_status.HTTP_504_GATEWAY_TIMEOUT,
    )


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    chat_history: list[ChatMessage] = Field(default_factory=list)
    top_k: int | None = Field(default=None, ge=1, le=50)
    rerank_top_k: int | None = Field(default=None, ge=1, le=50)


class ChatResponse(BaseModel):
    answer: str
    sources: list[SearchResult]


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/ready", tags=["system"])
def ready() -> JSONResponse:
    readiness = check_readiness()
    return JSONResponse(
        status_code=200 if readiness.is_ready else 503,
        content=readiness.to_dict(),
    )


@app.get("/status", tags=["system"])
def status(
    _: Annotated[None, Depends(require_internal_api_key)],
) -> dict:
    return get_system_status().to_dict()


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
def chat(
    request: ChatRequest,
    _: Annotated[None, Depends(require_internal_api_key)],
    orchestrator: Annotated[RAGOrchestrator, Depends(get_rag_orchestrator)],
) -> ChatResponse:
    answer, sources = orchestrator.run(
        query=request.message,
        top_k=request.top_k,
        rerank_top_k=request.rerank_top_k,
        chat_history=[message.model_dump() for message in request.chat_history],
    )
    return ChatResponse(answer=answer, sources=sources)
