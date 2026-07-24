import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from app.core.logging import bind_request_id


logger = logging.getLogger(__name__)

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

REQUEST_ID_HEADER = b"x-request-id"


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
