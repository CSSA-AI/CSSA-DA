"""Derive a stable, source-prefixed doc_id for a knowledge-base row.

The id must be identical every time the same underlying document is
retrieved -- eval metrics (app/services/rag/eval/*.py) match retrieved
articles against ground truth by id, and structured retrieval logs
(see CSS-15) key off it too. A random id per request makes both useless.

Today every row comes from WeChat. The WeChat article URL's last path
segment is already a stable, unique-enough slug, so it's used directly
with a `wx_` prefix (e.g. `wx_vGqp2DXA34OE8iHxaSaUFg`). Prefixing leaves
room for future sources with their own scheme -- e.g. a handbook source
would use `hb_<course_code>_<year>_<section>` rather than a link-derived
slug, since handbook entries don't have one.

Any link that isn't a recognised WeChat article URL (or is missing) falls
back to a short deterministic hash so the system still returns *a* stable
id instead of raising -- callers should not have to special-case retrieval
failures just because one row is missing a link.
"""

import hashlib
from typing import Optional
from urllib.parse import parse_qs, urlparse

_WECHAT_HOST = "mp.weixin.qq.com"
_HASH_LENGTH = 16


def derive_doc_id(*, link: Optional[str], text: str) -> str:
    """Return a stable id for a knowledge-base row.

    `link` is preferred when it's a recognised source URL. `text` (the
    row's content) is the fallback key when there's no usable link, so a
    missing link still produces a deterministic id rather than a crash
    (the ingestion pipeline defaults a missing link to `""`, not `None`,
    so this path is reachable in production, not just a defensive extra).
    """
    if link:
        parsed = urlparse(link)
        if parsed.netloc == _WECHAT_HOST:
            slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
            # WeChat articles use two URL shapes. Path-style
            # (/s/<slug>) gives a real per-article slug. Query-style
            # (/s?...&sn=...) has nothing in the path -- its last
            # segment is literally "s", which would collapse every
            # query-style article onto the same id. Read the `sn`
            # query param instead; it's WeChat's own per-article id
            # in that URL shape.
            if slug and slug != "s":
                return f"wx_{slug}"
            sn = parse_qs(parsed.query).get("sn", [""])[0]
            if sn:
                return f"wx_{sn}"
        return f"kb_{_digest(link)}"

    return f"kb_{_digest(text)}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_HASH_LENGTH]
