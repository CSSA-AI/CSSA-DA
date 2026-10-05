import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import bind_request_id


logger = logging.getLogger(__name__)

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

REQUEST_ID_HEADER = b"x-request-id"

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"strict-transport-security", b"max-age=63072000; includeSubDomains"),
]


def _get_header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


class RequestContextMiddleware:
    """Binds a request_id to every HTTP request and logs one access-log line per request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _get_header(scope, REQUEST_ID_HEADER) or str(uuid.uuid4())
        status_code: int | None = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append(
                    (REQUEST_ID_HEADER, request_id.encode("latin-1")),
                )
                message = {**message, "headers": headers}
            await send(message)

        start = time.perf_counter()
        with bind_request_id(request_id):
            await self.app(scope, receive, send_wrapper)
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "request completed",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )


class RequestBodyTooLargeError(HTTPException):
    """Raised once a streamed request body crosses the configured byte limit.

    Subclasses HTTPException (not a bare Exception) on purpose: FastAPI reads
    the request body inside a try/except that turns *any* other exception
    into a generic 400 "There was an error parsing the body" — it special-
    cases HTTPException with `except HTTPException: raise` specifically so a
    middleware-raised HTTPException reaches app.exception_handlers unchanged
    (see fastapi.routing.get_request_handler).
    """

    def __init__(self, received_bytes: int):
        super().__init__(
            status_code=413,
            detail="Request body exceeds the maximum allowed size.",
        )
        self.received_bytes = received_bytes


def _payload_too_large_response() -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={
            "error": {
                "code": "payload_too_large",
                "message": "Request body exceeds the maximum allowed size.",
            }
        },
    )


class MaxBodySizeMiddleware:
    """Rejects an oversized request body before routing, parsing, or auth sees it.

    FastAPI resolves body parsing before dependencies, so an unauthenticated
    caller can otherwise make the server buffer and JSON-parse an arbitrarily
    large body before ever being rejected with 401. A request with a
    Content-Length over the limit is rejected immediately, without invoking
    the wrapped app at all. A chunked request (no Content-Length) is let
    through, but `receive` is wrapped to tally bytes as they arrive and raise
    once the running total crosses the limit, so the body is never fully
    buffered just to be rejected.

    Reads settings.MAX_REQUEST_BODY_BYTES live on every request (not once at
    construction time), the same pattern app/core/rate_limit.py uses for the
    rate limit strings, so tests can monkeypatch it without rebuilding the
    middleware stack.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        max_body_bytes = settings.MAX_REQUEST_BODY_BYTES

        content_length = _get_header(scope, b"content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = None
            if declared_size is not None and declared_size > max_body_bytes:
                logger.warning(
                    "Rejecting oversized request: Content-Length %s > %s bytes",
                    declared_size,
                    max_body_bytes,
                )
                await _payload_too_large_response()(scope, receive, send)
                return

        received = 0

        async def receive_wrapper() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_body_bytes:
                    raise RequestBodyTooLargeError(received)
            return message

        await self.app(scope, receive_wrapper, send)


class SecurityHeadersMiddleware:
    """Adds standard security headers to every HTTP response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(SECURITY_HEADERS)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
