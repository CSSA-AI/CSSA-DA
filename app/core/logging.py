import json
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Iterator


_request_id: ContextVar[str | None] = ContextVar(
    "request_id",
    default=None,
)

STRUCTURED_FIELDS = (
    "method",
    "path",
    "status_code",
    "duration_ms",
    "error_code",
    # The chat_interactions payload of a row that could not be written. The
    # formatter drops any field not listed here, so without this entry the
    # write-failure line would lose exactly the query it exists to preserve
    # (ROADMAP_rag.md Phase 4.5).
    "chat_interaction",
)


class AppJsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or _request_id.get()
        if request_id:
            payload["request_id"] = request_id

        for field in STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_app_logging(level: int | str = logging.INFO) -> None:
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    app_logger = logging.getLogger("app")
    for existing_handler in app_logger.handlers[:]:
        app_logger.removeHandler(existing_handler)
        existing_handler.close()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(AppJsonLogFormatter())
    app_logger.addHandler(handler)
    app_logger.setLevel(level)
    app_logger.propagate = False


def get_request_id() -> str | None:
    return _request_id.get()


@contextmanager
def bind_request_id(request_id: str) -> Iterator[None]:
    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)
