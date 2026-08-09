# Implemented designs

Design write-ups for work that has **shipped**. These are the design of record:
they describe why the code looks the way it does, and the trade-offs that were
accepted along the way.

Keep them updated when the design changes — if a document no longer matches the
code, it is worse than no document.

| Document | Covers |
|---|---|
| [chat-api-hardening.md](chat-api-hardening.md) | `/chat` structured logging, security headers, CORS, rate limiting |
| [deployment-packaging.md](deployment-packaging.md) | Dependency locking, slim multi-stage images |
| [storage-abstraction.md](storage-abstraction.md) | Pipeline storage interface (`S3Storage` still pending — see [ROADMAP_platform](../../roadmap/ROADMAP_platform.md) Phase 3) |
