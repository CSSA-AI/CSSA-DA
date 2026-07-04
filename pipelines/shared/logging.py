import json
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Iterator


_run_id: ContextVar[str | None] = ContextVar(
    "pipeline_run_id",
    default=None,
)

STRUCTURED_FIELDS = (
    "event",
    "stage",
    "duration_seconds",
    "record_count",
    "batch_number",
    "batch_count",
    "inserted_count",
    "error_count",
    "error_type",
)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        run_id = getattr(record, "run_id", None) or _run_id.get()
        if run_id:
            payload["run_id"] = run_id

        for field in STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_pipeline_logging(level: int = logging.INFO) -> None:
    pipeline_logger = logging.getLogger("pipelines")
    for existing_handler in pipeline_logger.handlers[:]:
        pipeline_logger.removeHandler(existing_handler)
        existing_handler.close()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    pipeline_logger.addHandler(handler)
    pipeline_logger.setLevel(level)
    pipeline_logger.propagate = False


@contextmanager
def pipeline_run_context(run_id: str) -> Iterator[None]:
    token = _run_id.set(run_id)
    try:
        yield
    finally:
        _run_id.reset(token)
