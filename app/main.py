import asyncio
from contextlib import asynccontextmanager
from http import HTTPStatus
import logging
from typing import Annotated, Literal

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Request,
    status as http_status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field
from slowapi.errors import RateLimitExceeded

from app.api.deps import (
    Principal,
    close_rag_orchestrator,
    get_rag_orchestrator,
    preload_rag_orchestrator,
    require_caller,
)
from app.core.config import settings
from app.core.logging import configure_app_logging
from app.core.middleware import (
    MaxBodySizeMiddleware,
    RequestBodyTooLargeError,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.rate_limit import (
    chat_global_rate_limit,
    chat_rate_limit,
    chat_rate_limit_key,
    global_rate_limit_key,
    limiter,
    validate_rate_limit_config,
)
from app.schemas.search_result import SearchResult
from app.services.chat_interactions import schedule_chat_interaction
from app.services.readiness import check_readiness
from app.services.system_status import get_system_status
from app.services.rag.orchestrator import RAGOrchestrator
from app.services.rag.errors import (
    GenerationTimeoutError,
    GenerationUnavailableError,
    RAGServiceError,
    RetrievalUnavailableError,
)
from app.services.rag.model_registry import model_registry


configure_app_logging(settings.LOG_LEVEL)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Must stay OUTSIDE the preload try/except below: a malformed limit
    # string has to stop the container at startup, not be logged and
    # tolerated (slowapi would otherwise skip the layer per-request).
    validate_rate_limit_config()
    try:
        await asyncio.to_thread(model_registry.preload_models)
    except Exception:
        # Both the retriever and the reranker pull their model from the
        # registry, so building the orchestrator now would retry the same
        # failing load a second time and still not yield a usable pipeline.
        # Nothing diagnostic is lost: /ready reports the database side.
        logger.exception(
            "RAG model preload failed; skipping RAG orchestrator preload"
        )
    else:
        try:
            await asyncio.to_thread(preload_rag_orchestrator)
        except Exception:
            logger.exception("RAG orchestrator preload failed")
    yield
    close_rag_orchestrator()


app = FastAPI(
    title="CSSA-DA RAG API",
    version="0.1.0",
    description="RAG chatbot API for Chinese students and scholars in Australia.",
    lifespan=lifespan,
)

# slowapi reads the limiter from app.state during request handling.
app.state.limiter = limiter

# Starlette wraps middleware in reverse: the LAST add_middleware call becomes
# the OUTERMOST layer (runs first on requests, last on responses).
# Order (outermost -> innermost): CORS > SecurityHeaders > RequestContext >
# MaxBodySize. CORS stays outermost so preflight OPTIONS requests are answered
# before entering the rest of the stack and CORS headers land on every
# response, including error responses.
#
# MaxBodySize is innermost of the four. Its Content-Length fast path answers
# without invoking anything further in, so every layer whose headers must
# appear on that 413 has to sit OUTSIDE it — put it outermost and the fast
# path ships a response with no security headers and no X-Request-ID, unlike
# every other response the app produces. Being innermost costs it nothing:
# middleware all run ahead of routing, so an oversized body still never
# reaches routing, parsing, or auth, and the body is still never read.
app.add_middleware(MaxBodySizeMiddleware)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
    expose_headers=["X-Request-ID"],
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


# FastAPI/Starlette's built-in handlers for these two return {"detail": ...},
# which breaks the {"error": {code, message}} contract every other handler in
# this file follows. Registering our own replaces those defaults.
#
# The HTTPException one is registered on Starlette's class, not FastAPI's
# subclass of it. Handler lookup walks the MRO of the exception that was
# actually raised, so registering on the subclass would miss everything
# Starlette itself raises from its own base class — 404 from an unmatched
# route and 405 from a wrong method — and those would keep returning
# {"detail": ...}. Registering on the base covers both, and a more specific
# registration still wins: RateLimitExceeded also inherits from this class
# but comes first in its own MRO, so it keeps its "rate_limited" code.
def _http_status_error_code(status_code: int) -> str:
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:
        phrase = "error"
    return phrase.lower().replace(" ", "_").replace("-", "_")


@app.exception_handler(RequestValidationError)
def handle_validation_error(
    _: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    # Field errors carry an "input" entry that echoes the request body back
    # verbatim; for a 20-item chat_history that's the entire oversized
    # payload. Keep loc/msg/type (useful for debugging, derived only from
    # field constraints) and drop input.
    details = [
        {key: value for key, value in error.items() if key in ("loc", "msg", "type")}
        for error in exc.errors()
    ]
    logger.warning("Request validation failed: %s", details)
    return JSONResponse(
        status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request failed validation.",
                "details": details,
            }
        },
    )


@app.exception_handler(StarletteHTTPException)
def handle_http_exception(
    _: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    logger.warning("HTTP exception: %s %s", exc.status_code, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "error": {
                "code": _http_status_error_code(exc.status_code),
                "message": exc.detail,
            }
        },
    )


@app.exception_handler(RequestBodyTooLargeError)
def handle_request_body_too_large(
    _: Request,
    exc: RequestBodyTooLargeError,
) -> JSONResponse:
    # A chunked request has no Content-Length for the middleware to reject
    # upfront, so this fires once its streamed byte count crosses the limit.
    logger.warning(
        "Rejecting oversized chunked request body: %s bytes",
        exc.received_bytes,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "payload_too_large",
                "message": exc.detail,
            }
        },
    )


@app.exception_handler(RateLimitExceeded)
def handle_rate_limit_exceeded(
    _: Request,
    exc: RateLimitExceeded,
) -> JSONResponse:
    # Override slowapi's default body with our shared safe error shape.
    # exc.detail is the limit string ("10 per 1 minute" vs "500 per 1 day"),
    # which tells ops whether one IP is being throttled or the site-wide
    # budget is exhausted — it goes to the logs only, never the response.
    logger.warning("Rate limit exceeded: %s", exc.detail)
    return JSONResponse(
        status_code=http_status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": {
                "code": "rate_limited",
                "message": "Too many requests. Please slow down and try again shortly.",
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


@app.exception_handler(Exception)
def handle_unexpected_error(
    _: Request,
    error: Exception,
) -> JSONResponse:
    # Catch-all safety net for exceptions with no specific handler. Starlette
    # resolves handlers by the exception's class MRO, so the specific handlers
    # above always take precedence and registration order does not matter.
    logger.error(
        "Unhandled exception while processing request",
        exc_info=(type(error), error, error.__traceback__),
    )
    return JSONResponse(
        status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred. Please try again later.",
            }
        },
    )


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4_000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    chat_history: list[ChatMessage] = Field(default_factory=list, max_length=20)
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
    caller: Annotated[Principal, Depends(require_caller)],
) -> dict:
    return get_system_status().to_dict()


@app.post("/v1/chat", response_model=ChatResponse, tags=["chat"])
# Decorator order is load-bearing: slowapi evaluates callable limits in
# bottom-up registration order and charges a counter before judging it, so
# the per-IP limit must sit closest to the function — its 429 then breaks
# before the site-wide counter is charged. Swapped, one spamming IP could
# burn the whole site's daily budget with rejected requests (see
# docs/design/implemented/global-rate-limit.md and
# test_per_ip_429s_do_not_burn_the_global_budget).
@limiter.limit(chat_global_rate_limit, key_func=global_rate_limit_key)
@limiter.limit(chat_rate_limit, key_func=chat_rate_limit_key)
def chat(
    request: Request,  # required by slowapi (looked up by this exact name)
    payload: ChatRequest,
    background_tasks: BackgroundTasks,
    caller: Annotated[Principal, Depends(require_caller)],
    orchestrator: Annotated[RAGOrchestrator, Depends(get_rag_orchestrator)],
) -> ChatResponse:
    answer, sources = orchestrator.run(
        query=payload.message,
        top_k=payload.top_k,
        rerank_top_k=payload.rerank_top_k,
        chat_history=[message.model_dump() for message in payload.chat_history],
    )
    # Starlette runs background tasks after the response body has been sent,
    # so this adds nothing to /chat's latency. Only successful exchanges are
    # recorded — a 503/504 raises before reaching this line, so queries that
    # failed generation are not yet captured (ROADMAP_rag.md Phase 4.5 scopes
    # v1 to the success path).
    schedule_chat_interaction(
        background_tasks,
        query=payload.message,
        answer=answer,
        sources=sources,
        top_k=payload.top_k,
        rerank_top_k=payload.rerank_top_k,
    )
    return ChatResponse(answer=answer, sources=sources)
