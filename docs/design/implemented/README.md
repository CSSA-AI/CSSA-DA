# Implemented designs

Design write-ups for work that has **shipped**. These are the design of record:
they describe why the code looks the way it does, and the trade-offs that were
accepted along the way.

Keep them updated when the design changes — if a document no longer matches the
code, it is worse than no document.

| Document | Covers |
|---|---|
| [chat-api-hardening.md](chat-api-hardening.md) | `/chat` structured logging, security headers, CORS, rate limiting, the shared error-response contract, and the request body size cap |
| [global-rate-limit.md](global-rate-limit.md) | Site-wide `/chat` rate limit and the OpenAI spend cap |
| [retrieval-logging.md](retrieval-logging.md) | What the RAG pipeline logs per stage, and why no user content goes to CloudWatch |
| [startup-and-readiness.md](startup-and-readiness.md) | What the app does before it accepts traffic: preload, model warm-up, liveness vs readiness, connection timeouts |
| [database-migrations.md](database-migrations.md) | Why a rollback cannot undo a migration, the two-deploy expand/contract sequences, and the locking axis this rule does not cover |
| [caller-identity.md](caller-identity.md) | How authentication decides who the caller is once, and how rate limiting reads that decision instead of re-reading the request |
| [aws-foundation.md](aws-foundation.md) | Everything standing on AWS, from `terraform init` to a public URL: the VPC and its routing, NAT, remote state, ECR and image architecture, RDS, how secrets and config reach a container, the Fargate service, the load balancer, the data bucket, and how the schema and the corpus got into a database that has no public address — with the beginner-level networking, IAM and container-runtime background |
| [deployment-packaging.md](deployment-packaging.md) | Dependency locking, slim multi-stage images |
| [storage-abstraction.md](storage-abstraction.md) | Pipeline storage interface (`S3Storage` still pending — see [ROADMAP_platform](../../roadmap/ROADMAP_platform.md) Phase 3) |
| [reranker-selection.md](reranker-selection.md) | Replacing the English-only reranker: six candidates on realistic Chinese and cross-lingual questions, why the larger BGE models were rejected on CPU latency, why truncation is pinned at 256 tokens, and why retriever recall is now the bottleneck |
