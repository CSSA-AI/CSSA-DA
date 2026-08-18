from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


# In-memory limiter keyed by client IP. Single-instance is sufficient for this
# deployment; a Redis-backed store would only be needed for multi-instance
# horizontal scaling (see docs/roadmap/ROADMAP_platform.md).
limiter = Limiter(key_func=get_remote_address)


def chat_rate_limit() -> str:
    """Return the /chat rate limit, read live so tests can override it.

    Passing this callable (not a literal string) to @limiter.limit re-reads
    settings.CHAT_RATE_LIMIT on every request, letting tests monkeypatch a
    tight limit without affecting other tests.
    """
    return settings.CHAT_RATE_LIMIT


def chat_global_rate_limit() -> str:
    """Return the site-wide /chat rate limit, read live like chat_rate_limit."""
    return settings.CHAT_GLOBAL_RATE_LIMIT


def global_rate_limit_key() -> str:
    """Constant key so every request shares one counter.

    The per-IP limit can be dodged by rotating IPs; this layer caps total
    spend regardless of how many addresses the traffic comes from
    (ROADMAP_platform.md 19.4). slowapi calls a route-level key_func with no
    arguments (unlike the limiter-level default, which receives the request).
    """
    return "global"
