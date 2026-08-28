"""Derive a stable, source-prefixed doc_id for a knowledge-base row.

The id must be identical every time the same underlying document is
retrieved -- eval metrics (app/services/rag/eval/*.py) match retrieved
articles against ground truth by id, and structured retrieval logs
(see CSS-15) key off it too. A random id per request makes both useless.

Today every row comes from WeChat, which has (at least) two known article
URL shapes -- path-style (`/s/<slug>`) and query-style (`/s?...&sn=...`).
Each is matched against an explicit allowlist and turned into a `wx_`
prefixed id from its own per-article token. Prefixing leaves room for
future sources with their own scheme -- e.g. a handbook source would use
`hb_<course_code>_<year>_<section>` rather than a link-derived slug, since
handbook entries don't have one.

Deliberately an allowlist, not a denylist. An earlier version treated any
non-empty path segment as a valid slug and only excluded the one known-bad
value ("s"). That missed a third WeChat shape (`/mp/appmsg/show`) whose
last path segment ("show") isn't "s" either -- every article using that
shape silently collapsed onto the single id `wx_show`. A denylist can only
ever exclude shapes someone has already seen; matching known-good shapes
and falling back for everything else closes the whole class instead of
one instance of it. See the CSS-7 review (PR #74) for the full writeup.

Any link that isn't a recognised WeChat article URL (or is missing) falls
back to a short deterministic hash so the system still returns *a* stable
id instead of raising -- callers should not have to special-case retrieval
failures just because one row is missing a link. A WeChat link that fails
to match either known shape also falls back this way, but logs a warning
first -- see `derive_doc_id`.
"""

import hashlib
import logging
from typing import Optional
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

_WECHAT_HOST = "mp.weixin.qq.com"
_HASH_LENGTH = 16


def derive_doc_id(*, link: Optional[str], text: str) -> str:
    """Return a stable id for a knowledge-base row.

    `link` is preferred when it's a recognised source URL. `text` (the
    row's content) is the fallback key when there's no usable link, so a
    missing link still produces a deterministic id rather than a crash
    (the ingestion pipeline defaults a missing link to `""`, not `None`,
    so this path is reachable in production, not just a defensive extra).

    A `link` on the WeChat host that doesn't match either known shape logs
    a warning and falls back to the hash, instead of silently guessing at
    a slug. That warning is the monitoring signal for "a WeChat URL shape
    showed up that this function doesn't know how to id yet" -- a rising
    rate of it in the logs is the cue to add a new shape here, the same
    way the `/mp/appmsg/show` shape was found.
    """
    if link:
        parsed = urlparse(link)
        if parsed.netloc == _WECHAT_HOST:
            # Path-style: exactly `/s/<slug>`, nothing more, nothing less.
            # Matching the full shape (not just "isn't the bad value we
            # know about") is what keeps a fourth, still-unseen shape from
            # silently reusing this branch.
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "s" and parts[1]:
                return f"wx_{parts[1]}"

            # Query-style: `/s?...&sn=...`. `sn` is WeChat's own
            # per-article id in this shape.
            sn = parse_qs(parsed.query).get("sn", [""])[0]
            if sn:
                return f"wx_{sn}"

            logger.warning(
                "doc_id: unrecognized WeChat link shape, "
                "falling back to hash id: %s",
                link,
            )
        return f"kb_{_digest(link)}"

    return f"kb_{_digest(text)}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_HASH_LENGTH]
