from fastapi import Request
from limits import parse_many
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


USER_ID_HEADER = "X-User-Id"

# Cap the header before it becomes a counter key. The BFF is trusted to say WHO
# the user is, but the value still arrives over the wire and every distinct one
# creates a new entry in the in-memory storage dict. 64 chars fits a Django
# user id or a UUID with room to spare.
MAX_USER_KEY_LENGTH = 64


def client_rate_limit_key(request: Request) -> str:
    """Count per user when the caller identifies one, per IP otherwise.

    myCSSA's BFF proxies every browser request, so once it ships every call
    reaches us from ONE address and get_remote_address stops discriminating:
    the entire user base would share a single CHAT_RATE_LIMIT bucket. The BFF
    forwards X-User-Id instead (ROADMAP_platform.md item 16, CSS-11).

    The header is trusted, not verified. Only a caller holding CHAT_API_KEY
    gets this far, which is the standard trusted-proxy arrangement.

    Two details are easy to get wrong and both are load-bearing:

    - Falling back to the IP is mandatory, not a nicety. Nothing sends
      X-User-Id until the BFF (CSS-9) ships, so a constant or empty-string
      fallback would drop every request into one shared bucket, which is
      strictly worse than counting per IP.
    - The two key spaces are prefixed. Without "user:"/"ip:", a request
      claiming X-User-Id: 10.0.0.1 would share a counter with real traffic
      coming from 10.0.0.1.

    A caller can still rotate X-User-Id to dodge this layer; the site-wide
    limit from CSS-10 is what caps total spend in that case.
    """
    user_id = (request.headers.get(USER_ID_HEADER) or "").strip()
    if user_id:
        return f"user:{user_id[:MAX_USER_KEY_LENGTH]}"
    return f"ip:{get_remote_address(request)}"


# In-memory limiter keyed per user, falling back to client IP. Single-instance
# is sufficient for this deployment; a Redis-backed store would only be needed
# for multi-instance horizontal scaling (see docs/roadmap/ROADMAP_platform.md).
# INVARIANT: the per-caller and site-wide counters live in process memory.
# Dockerfile.api runs ONE uvicorn worker and docker-compose ONE replica, so
# they are truly global today — adding --workers N, compose replicas, or
# extra ECS tasks silently multiplies every effective limit by N. Switch to
# a Redis storage_uri before scaling out.
limiter = Limiter(key_func=client_rate_limit_key)


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

    The per-caller limit can be dodged by rotating IPs or X-User-Id values;
    this layer caps total spend regardless of how many addresses or user ids
    the traffic claims (ROADMAP_platform.md 19.4). slowapi calls a route-level
    key_func with no arguments (unlike the limiter-level default, which
    receives the request).
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
