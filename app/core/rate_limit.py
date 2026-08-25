from limits import parse_many
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


# In-memory limiter keyed by client IP. Single-instance is sufficient for this
# deployment; a Redis-backed store would only be needed for multi-instance
# horizontal scaling (see docs/roadmap/ROADMAP_platform.md).
# INVARIANT: the per-IP and site-wide counters live in process memory.
# Dockerfile.api runs ONE uvicorn worker and docker-compose ONE replica, so
# they are truly global today — adding --workers N, compose replicas, or
# extra ECS tasks silently multiplies every effective limit by N. Switch to
# a Redis storage_uri before scaling out.
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


def validate_rate_limit_config() -> None:
    """Fail fast on malformed rate-limit strings.

    slowapi parses callable limits per request inside a try/except and
    reacts to a parse failure by logging an error and SKIPPING the layer —
    fail-open. A typo like "500/dya" would silently disable the limit while
    requests keep reaching OpenAI. Called from the app lifespan so a bad
    value stops the container at startup instead.
    """
    for name, value in (
        ("CHAT_RATE_LIMIT", settings.CHAT_RATE_LIMIT),
        ("CHAT_GLOBAL_RATE_LIMIT", settings.CHAT_GLOBAL_RATE_LIMIT),
    ):
        try:
            parsed = parse_many(value)
        except ValueError as error:
            raise RuntimeError(
                f"Invalid rate limit string in {name}: {value!r}"
            ) from error
        # "0/day" parses fine but would 429 every single request.
        if any(item.amount < 1 for item in parsed):
            raise RuntimeError(
                f"{name} must allow at least 1 request, got {value!r}"
            )
