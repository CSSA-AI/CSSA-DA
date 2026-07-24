from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


# In-memory limiter keyed by client IP. Single-instance is sufficient for this
# deployment; a Redis-backed store would only be needed for multi-instance
# horizontal scaling (see future_plan.md).
limiter = Limiter(key_func=get_remote_address)


def chat_rate_limit() -> str:
    """Return the /chat rate limit, read live so tests can override it.

    Passing this callable (not a literal string) to @limiter.limit re-reads
    settings.CHAT_RATE_LIMIT on every request, letting tests monkeypatch a
    tight limit without affecting other tests.
    """
    return settings.CHAT_RATE_LIMIT
