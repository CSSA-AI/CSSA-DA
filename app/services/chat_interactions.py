"""Record one row per /chat request, written after the response is sent.

This is the data line's feeding tube (ROADMAP_rag.md Phase 4.5): the hardest
problem in the whole data roadmap is "where do real queries come from", and
/chat starts producing them the moment it is live.

The asymmetry that drives every decision in this module: feedback, dashboards
and implicit signals are all additive — they can be built whenever. **A query
that was never written down cannot be recovered.** So recording must never be
allowed to break /chat, and must never be allowed to fail quietly either — a
failed write is logged loudly, by request_id.

What it deliberately does NOT do is log the payload. Writing the query to the
logs as a fallback would put the same user content in a second store with a
different retention policy and a different access-control list, which is
exactly what retrieval-logging.md rules out. Queries answered while the
database is unreachable are lost; that is the accepted price of keeping one
copy of user content, in one place.

Known trade-off — one connection per write, no pool. The retriever keeps a
ThreadedConnectionPool because it is on the request path; this is not, so it
pays a TCP handshake and an auth round trip per answered request instead of
holding connections open. At v1 volume (hundreds of rows a day, capped by the
site-wide rate limit) that is the cheaper side of the trade: a pool sized for
a workload this sparse would keep connections idle against a database whose
connection budget is already being counted for ECS sizing
(ROADMAP_platform.md). Revisit if /chat volume grows by an order of
magnitude, or if the threadpool slot each write occupies starts to matter.
"""

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import logging
import uuid
from typing import Any, Iterable, Optional

import psycopg2
from fastapi import BackgroundTasks
from psycopg2.extras import Json

from app.core.config import rag_config, settings
from app.core.logging import get_request_id
from app.schemas.search_result import SearchResult


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatInteractionRecord:
    """One /chat exchange, ready to insert."""

    request_id: str
    query: str
    answer: str | None = None
    retrieved: list[dict[str, Any]] | None = None
    config: dict[str, Any] | None = None


@lru_cache(maxsize=1)
def prompt_version() -> str:
    """Fingerprint of the system prompt, derived rather than declared.

    A hand-maintained `prompt_version: v3` in rag-config.yaml drifts the first
    time someone edits the prompt and forgets to bump it — and a fingerprint
    that silently lies is worse than no fingerprint, because the comparison it
    invalidates is the one you make six months later without re-checking.
    Hashing the prompt text cannot drift.
    """
    system_prompt = rag_config["generator"].get("system_prompt", "")
    digest = hashlib.sha256(system_prompt.encode("utf-8"))
    return f"sha256:{digest.hexdigest()[:12]}"


def build_config_fingerprint(
    *,
    top_k: Optional[int] = None,
    rerank_top_k: Optional[int] = None,
) -> dict[str, Any]:
    """The four version coordinates plus the knobs that change answers.

    Five lines of work, but without it you cannot tell whether a row was
    produced before or after a reranker swap, and the whole batch stops being
    comparable (ROADMAP_rag.md Phase 4.5, CONTRIBUTING.md "Four version
    coordinates").

    `top_k` / `rerank_top_k` are the *effective* values — the per-request
    override when the caller sent one, the configured default otherwise.
    Recording the default when the request overrode it would misattribute the
    result to a configuration that never ran.
    """
    retriever = rag_config["retriever"]
    reranker = rag_config["reranker"]
    generator = rag_config["generator"]

    return {
        "embedding_model": retriever.get("embedding_model"),
        "embedding_revision": retriever.get("embedding_revision"),
        "reranker_model": reranker.get("model_name"),
        "reranker_revision": reranker.get("model_revision"),
        "generator_model": generator.get("model_name"),
        "top_k": top_k if top_k is not None else retriever.get("top_k"),
        "rerank_top_k": (
            rerank_top_k
            if rerank_top_k is not None
            else reranker.get("top_k")
        ),
        "prompt_version": prompt_version(),
        # Deploy-time values: the corpus hash unifies online rows and the
        # offline eval set onto one ruler, and the git sha is the "which
        # code" coordinate. Both are null until the deploy sets them — a
        # null is honest, a wrong value is not.
        "corpus_sha256": settings.CORPUS_SHA256,
        "git_sha": settings.GIT_SHA,
    }


def build_retrieved(
    sources: Iterable[SearchResult],
) -> list[dict[str, Any]]:
    """The documents behind an answer, in post-rerank order.

    `doc_id` is the stable, source-prefixed id derived from the article link
    (`wx_<slug>` for WeChat) since CSS-7 / PR #74, so these values join back
    to knowledge_base and line up with the ids in the retrieval logs.
    """
    return [
        {
            "doc_id": source.article.id,
            "score": source.score,
            "rank": source.rank,
        }
        for source in sources
    ]


def record_chat_interaction(
    record: ChatInteractionRecord,
    *,
    database_url: Optional[str] = None,
) -> None:
    """Insert one row. Never raises — a failed write must not reach the user.

    Runs in a BackgroundTask, i.e. after the response has been sent, so a slow
    or unavailable database costs /chat nothing. Failures are logged by
    request_id only -- never with the payload, see the module docstring.
    """
    database_url = database_url or settings.DATABASE_URL
    try:
        if not database_url:
            raise RuntimeError("DATABASE_URL is not configured")

        # Bounded like every other connection this service opens: without it
        # libpq waits for the OS TCP timeout (~127s on Linux) on a database
        # host that drops packets. This path runs on every answered request
        # and each stuck write holds an anyio threadpool slot, so an
        # unbounded connect here is worse than on a probe.
        connection = psycopg2.connect(
            database_url,
            connect_timeout=rag_config["pgvector"].get(
                "connect_timeout_seconds", 5
            ),
        )
        # psycopg2's `with conn:` ends the transaction but does NOT close the
        # connection. pipeline_runs can lean on GC for that; this path runs on
        # every answered request, so it closes explicitly rather than betting
        # on when the refcount drops.
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO chat_interactions (
                            request_id,
                            query,
                            answer,
                            retrieved,
                            config
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (request_id) DO NOTHING
                        """,
                        (
                            record.request_id,
                            record.query,
                            record.answer,
                            Json(record.retrieved)
                            if record.retrieved is not None
                            else None,
                            Json(record.config)
                            if record.config is not None
                            else None,
                        ),
                    )
                    inserted = cursor.rowcount
        finally:
            connection.close()
    except Exception:
        # request_id only. The payload carries the user's query, and no user
        # content goes to the logs -- that guarantee is what makes "id only,
        # zero privacy cost" true (docs/design/implemented/retrieval-logging.md).
        # The cost is accepted deliberately: queries answered while the
        # database is unreachable are lost rather than duplicated into a
        # second store with its own retention and access control.
        logger.exception(
            "Failed to record chat interaction",
            extra={"request_id": record.request_id},
        )
        return

    if not inserted:
        # RequestContextMiddleware honours a caller-supplied X-Request-ID, so
        # a client that reuses one collides on the primary key. DO NOTHING
        # keeps that from aborting the transaction, but the query still must
        # not vanish — it goes to the log like any other unwritten payload.
        logger.warning(
            "Duplicate chat interaction request_id, row not written",
            extra={"request_id": record.request_id},
        )


def build_chat_interaction_record(
    *,
    query: str,
    answer: str | None,
    sources: Iterable[SearchResult],
    top_k: Optional[int] = None,
    rerank_top_k: Optional[int] = None,
    request_id: Optional[str] = None,
) -> ChatInteractionRecord:
    return ChatInteractionRecord(
        # RequestContextMiddleware always binds one, so the fallback is for
        # paths that bypass it. A generated id keeps the query rather than
        # keying every such row on "" and colliding them into one row.
        request_id=request_id or get_request_id() or str(uuid.uuid4()),
        query=query,
        answer=answer,
        retrieved=build_retrieved(sources),
        config=build_config_fingerprint(
            top_k=top_k,
            rerank_top_k=rerank_top_k,
        ),
    )


def schedule_chat_interaction(
    background_tasks: BackgroundTasks,
    *,
    query: str,
    answer: str | None,
    sources: Iterable[SearchResult],
    top_k: Optional[int] = None,
    rerank_top_k: Optional[int] = None,
) -> None:
    """Build the row now, write it after the response has gone out.

    The record is built *synchronously*, inside the request, because
    `request_id` comes from a ContextVar bound by RequestContextMiddleware.
    Reading it inside the background task would work today but only by
    accident of how Starlette propagates context — capturing it here makes
    the primary key independent of that.

    Wrapped in its own try/except: `record_chat_interaction` already swallows
    write failures, but building the record must not be able to 500 a request
    whose answer was already produced.
    """
    try:
        record = build_chat_interaction_record(
            query=query,
            answer=answer,
            sources=sources,
            top_k=top_k,
            rerank_top_k=rerank_top_k,
        )
        background_tasks.add_task(record_chat_interaction, record)
    except Exception:
        logger.exception("Failed to schedule chat interaction recording")
