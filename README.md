# CSSA-DA: RAG Chatbot for International Students

A Retrieval-Augmented Generation (RAG) chatbot designed for Chinese students and scholars studying in Australia. The system answers questions about education, university requirements, visa processes, and student life by retrieving relevant articles and generating contextual responses via ChatGPT.

The repository holds two halves that meet in PostgreSQL:

- **Serving** — a FastAPI service (`app/`) that answers questions over the knowledge base.
- **Data** — a pipeline package (`pipelines/`) that harvests, cleans, validates, embeds and imports source articles.

---

## Architecture

**Query path** (`app/`):

```
User Query
    │
    ▼
[Retriever]   ──  PostgreSQL + pgvector semantic search over `knowledge_base`
    │
    ▼
[Reranker]    ──  CrossEncoder re-ranking (LoRA fine-tuning supported)
    │
    ▼
[Generator]   ──  OpenAI SDK generation with explicit chat history
    │
    ▼
Answer + Source Articles
```

**Data path** (`pipelines/`):

```
WeChat API ──▶ harvest ──▶ transform ──▶ validate ──▶ embed ──▶ import ──▶ knowledge_base
              data/raw    data/processed          pinned model        (PostgreSQL)
                              └── data/current (stable stage inputs) ──┘
```

The RAG pipeline is orchestrated in [app/services/rag/orchestrator.py](app/services/rag/orchestrator.py) and exposed through the FastAPI app in [app/main.py](app/main.py). PostgreSQL is the source of truth for `knowledge_base`; its schema is managed by Alembic migrations in [migrations/](migrations/).

---

## Repo Layout

```
CSSA-DA/
├── app/                                      # FastAPI service
│   ├── main.py                               # App, endpoints, exception handlers, model preload
│   ├── api/
│   │   └── deps.py                           # DI: RAG orchestrator, API-key auth
│   ├── core/
│   │   ├── config/
│   │   │   ├── settings.py                   # Pydantic settings (env / .env)
│   │   │   └── rag-config.yaml               # Pinned models, top_k, prompts, pgvector table
│   │   ├── logging.py                        # Structured JSON logging
│   │   ├── middleware.py                     # Request ID/context + security headers
│   │   └── rate_limit.py                     # slowapi limiter for /v1/chat
│   ├── schemas/
│   │   ├── article.py                        # Article Pydantic schema
│   │   └── search_result.py                  # RAG output schema (article + score + rank)
│   └── services/
│       ├── readiness.py                      # /ready: DB rows + model state
│       ├── system_status.py                  # /status: readiness + latest pipeline run
│       ├── question_generator/               # GPT-powered question generation for articles
│       └── rag/                              # Core RAG pipeline
│           ├── orchestrator.py               # Wires retriever → reranker → generator
│           ├── model_registry.py             # Shared model instances, startup preload
│           ├── errors.py                     # Safe error taxonomy (503 / 504 responses)
│           ├── adapters/langchain_adapter.py # Optional LCEL wrapper
│           ├── retriever/pg_retriever.py     # PostgreSQL + pgvector semantic search
│           ├── reranker/                     # CrossEncoder + LoRA training script
│           ├── generator/chatgpt_generator.py# OpenAI SDK generation + streaming
│           └── eval/                         # Retriever / reranker / generator evaluation
│
├── pipelines/                                # Data pipeline package (CLI: python -m pipelines)
│   ├── cli.py                                # harvest / transform / import / full run
│   ├── ingestion/wechat/                     # WeChat API client + harvester
│   ├── transform/wechat_articles.py          # Source-specific cleaning
│   ├── validation/                           # Data contract checks before expensive work
│   ├── embedding/                            # Embedding text construction
│   ├── loaders/                              # Postgres knowledge_base + pipeline_runs
│   ├── orchestration/                        # Runnable jobs (incl. run-wechat-pipeline)
│   └── shared/                               # Paths, storage abstraction, logging, reports
│
├── ops/                                      # Operator scripts
│   ├── check_config.py                       # Validate runtime config per profile
│   ├── db_status.py                          # Inspect knowledge_base rows / embeddings
│   ├── download_models.py                    # Pre-download pinned models
│   ├── rehearse_local_stack.py               # End-to-end local rehearsal
│   └── smoke_test_api.py                     # Hit /health, /ready, /v1/chat
│
├── migrations/                               # Alembic migrations (knowledge_base, pipeline_runs)
├── tests/
│   ├── unit/                                 # Fast, no external services
│   └── integration/                          # Require Postgres (RUN_INTEGRATION_TESTS=1)
│
├── data/                                     # Local pipeline artifacts
│   ├── raw/  processed/  current/            # Snapshots → transformed → stable stage inputs
│   └── checkpoints/  reports/                # Resumable state + run reports
│
├── .github/workflows/                        # Unit / integration / docker CI
├── Dockerfile.api                            # Production API image (slim, uv, multi-stage)
├── Dockerfile.pipeline                       # Data pipeline task image (slim, uv, multi-stage)
├── docker-compose.yml                        # PostgreSQL + pgvector, migrate, api, pipeline
├── pyproject.toml                            # Runtime deps (api/pipeline/dev groups); source for uv.lock
├── uv.lock                                   # Locked dependency versions (used by images + CI)
├── environment_cpu.yml / environment_gpu.yml # Optional DS notebook envs — not deployment artifacts
├── CONTRIBUTING.md                           # Branching, commits, PRs, versioning, releases
└── docs/
    ├── local-development.md                  # Local Docker workflows and command reference
    ├── roadmap/                              # What to build and when
    │   ├── ROADMAP_versions.md               #   Milestone boundaries v1–v4 — start here
    │   ├── BACKLOG.md                        #   Flattened issue list for Linear import
    │   ├── ROADMAP_platform.md               #   Containers, AWS, CI/CD, observability
    │   ├── ROADMAP_data.md                   #   Corpus, ground truth dataset, data sources
    │   └── ROADMAP_rag.md                    #   Query path, eval tooling, architecture experiments
    └── design/                               # Why things are designed this way (中文)
        ├── implemented/                       #   Shipped — design of record
        └── planned/                           #   Not started yet
```

---

## Setup

### 1. Install dependencies

The project is locked with [uv](https://docs.astral.sh/uv/); this is what CI and the
Docker images use, so it is the reproducible path:

```bash
uv sync --locked          # shared core + dev group (api + pipeline + test tooling)
```

`--locked` fails if `uv.lock` is out of date with `pyproject.toml`. After changing
dependencies, run `uv lock` and commit the updated lock file.

Role-specific installs (what the images do):

```bash
uv sync --locked --no-default-groups --group api        # API service only
uv sync --locked --no-default-groups --group pipeline   # Pipeline tasks only
```

<details>
<summary>Optional: conda environment for notebooks</summary>

`environment_cpu.yml` / `environment_gpu.yml` provide a data-science environment for
the notebooks under `scripts/`. They are **not** deployment artifacts and are not used
by CI or the Docker images.

```bash
conda env create -f environment_cpu.yml   # or environment_gpu.yml
conda activate cssa-ai
```

</details>

### 2. Environment variables

Copy `.env.example` to `.env` and fill in:

| Variable | Required for | Description |
|----------|--------------|-------------|
| `OPENAI_API_KEY` | API | OpenAI key used by the generator |
| `CHAT_API_KEY` | API | Internal key callers must send as `X-API-Key` on `/v1/chat` and `/status` |
| `DATABASE_URL` | API, pipeline | PostgreSQL connection string |
| `WECHAT_API_KEY` | harvester | WeChat article source |
| `ENV` | optional | `dev` by default |
| `MODEL_DIR` | optional | Local model directory (set to `/models` in the images) |
| `LOG_LEVEL` | optional | `INFO` by default |
| `ALLOWED_ORIGINS` | optional | Comma-separated CORS origins |
| `CHAT_RATE_LIMIT` | optional | Per-IP `/v1/chat` limit, `10/minute` by default |
| `CHAT_GLOBAL_RATE_LIMIT` | optional | Site-wide `/v1/chat` limit shared by all clients, `500/day` by default |

Check runtime configuration without printing secret values:

```bash
python ops/check_config.py --profile api        # also: pipeline, harvester, all
```

### 3. Docker

```bash
docker compose --profile cpu up --build
```

This starts PostgreSQL, applies Alembic migrations through the `migrate-cpu` service,
and then starts the FastAPI service. Open `http://localhost:8000/docs`. The pinned
embedding and reranker models are baked into the image and preloaded at startup, so no
download happens on the first `/v1/chat` request. Available profiles: `cpu` (API),
`pipeline` (pipeline tasks + migrations), `test` (throwaway Postgres). See
[docs/local-development.md](docs/local-development.md) for detailed Docker usage.

### 4. Rebuild the local knowledge base

Local knowledge-base rows are rebuilt from processed files in `data/`:

```bash
docker compose --profile pipeline run --rm migrate-cpu
docker compose --profile pipeline run --rm --no-deps pipeline-cpu transform-wechat
docker compose --profile pipeline run --rm pipeline-cpu import-knowledge-base --reset-checkpoint
docker compose --profile pipeline run --rm pipeline-cpu \
  python -m pipelines.orchestration.smoke_test_retrieval --query "墨尔本 校招"
docker compose --profile cpu up --build
python ops/db_status.py
python ops/smoke_test_api.py --message "墨尔本 校招"
```

The full harvest-to-import workflow is one command (`run-wechat-pipeline`); for
checkpoints, batching and the local-only variants see [pipelines/README.md](pipelines/README.md).

PostgreSQL is the canonical RAG store. The API dependency wiring uses `PGVectorRetriever`,
and readiness checks inspect PostgreSQL rows for the active embedding model/revision.

---

## Running the API

```bash
uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`, with interactive documentation at
`http://localhost:8000/docs`.

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `GET /health` | — | Liveness of the API process |
| `GET /ready` | — | Database + RAG data/model readiness (503 when not ready) |
| `GET /status` | `X-API-Key` | Readiness plus latest pipeline run metadata |
| `POST /v1/chat` | `X-API-Key` | Submit a message to the RAG pipeline |

`/v1/chat` is rate limited on two layers: per client IP (`CHAT_RATE_LIMIT`, default
`10/minute`) and site-wide across all clients (`CHAT_GLOBAL_RATE_LIMIT`, default
`500/day`) — rotating IPs cannot get past the shared counter, which caps total OpenAI
spend. Failures return a stable error shape — `{"error": {"code": ..., "message": ...}}`
— with internal details kept in the logs only: `503` when retrieval or generation is
unavailable, `504` on generation timeout, `429` when rate limited.

```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $CHAT_API_KEY" \
  -d '{"message": "墨尔本 校招"}'
```

---

## Testing

```bash
uv run pytest tests/unit -q                     # fast, no external services

# Integration tests need PostgreSQL + pgvector:
docker compose --profile test up -d postgres-test
RUN_INTEGRATION_TESTS=1 \
TEST_DATABASE_URL=postgresql://test:test@localhost:5433/testdb \
  uv run pytest tests/integration -q
```

CI runs three workflows on pull requests to `main`: unit tests + config-contract
validation, integration tests against a pgvector service, and a Docker build that
smoke-tests both images.

---

## Key Components

### Retriever ([app/services/rag/retriever/pg_retriever.py](app/services/rag/retriever/pg_retriever.py))
- Encodes user queries using the pinned SentenceTransformer model
- Searches PostgreSQL `knowledge_base` embeddings with pgvector
- Filters rows by embedding model and revision so retrieval matches the imported vectors
- Returns ranked `SearchResult` objects (article + similarity score)

### Reranker ([app/services/rag/reranker/cross_encoder_reranker.py](app/services/rag/reranker/cross_encoder_reranker.py))
- Re-scores retrieved results using a CrossEncoder model
- Supports loading a LoRA adapter for domain-specific fine-tuning
- Training script: [app/services/rag/reranker/train_lora.py](app/services/rag/reranker/train_lora.py)

### Generator ([app/services/rag/generator/chatgpt_generator.py](app/services/rag/generator/chatgpt_generator.py))
- OpenAI SDK integration without a LangChain dependency
- Explicit plain-dictionary chat history supplied by the calling application
- Context truncation plus synchronous and streaming output

The optional `LangChainRAGAdapter` wraps the framework-independent components as
LCEL runnables and returns shared pipeline state containing the answer and sources.

### Model registry ([app/services/rag/model_registry.py](app/services/rag/model_registry.py))
- Single shared instance of each model, so retriever and reranker do not load duplicates
- Preloaded during app startup (`lifespan`) instead of on the first request
- Exposes per-model load state (`not_loaded` / `loading` / `ready` / `failed`) to `/ready`

### Configuration ([app/core/config/rag-config.yaml](app/core/config/rag-config.yaml))
- Embedding and reranker models pinned by name **and** revision, so imports and retrieval
  use identical model files
- Retrieval/rerank `top_k`, pgvector table and pool sizes, generator model, timeouts and
  the system prompt

### Data pipelines ([pipelines/](pipelines/))
- One CLI: `python -m pipelines <command>` — `harvest-wechat`, `transform-wechat`,
  `import-knowledge-base`, `run-wechat-pipeline`
- Imports are batched, resumable via checkpoints, and idempotent on `(link, question_text)`
- Artifacts go through a storage abstraction (local today, S3-shaped keys) and every run
  writes a JSON report plus a `pipeline_runs` row

### Question Generator ([app/services/question_generator/](app/services/question_generator/))
- Uses GPT to generate natural Chinese questions for article/question datasets
- Detects content patterns (cost, requirements, process, comparison, etc.) to generate relevant question types
- Configurable via [app/services/question_generator/config.py](app/services/question_generator/config.py)

---

## Data Schema

**Article** ([app/schemas/article.py](app/schemas/article.py)) — the record shape used by the
pipeline and returned as a `/v1/chat` source:

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Stable, source-prefixed document id derived from `link` (e.g. `wx_<slug>`), not a random UUID — see [app/services/rag/doc_id.py](app/services/rag/doc_id.py) |
| `text` | str | Article body |
| `questions` | List[str] | GPT-generated questions (used for retrieval) |
| `source` | str | Origin website |
| `author` | str | Author name |
| `post_date` | date | Publication date |
| `created_at` | datetime | Ingestion timestamp |
| `language` | str | Content language |
| `tags` | List[str] | Topic tags |
| `link` | str | Original URL |

In PostgreSQL, one row of `knowledge_base` is one *(question, article)* pair: the article
fields above plus `question_text`, a 384-dim `embedding`, and the embedding model/revision
that produced it. Rows are unique on `(link, question_text)`.

---

## Documentation

| Document | Contents |
|----------|----------|
| [docs/roadmap/ROADMAP_versions.md](docs/roadmap/ROADMAP_versions.md) | **版本边界 v1–v4：谁能用、承诺什么、什么时候做（先看这个）** |
| [docs/roadmap/BACKLOG.md](docs/roadmap/BACKLOG.md) | 摊平的 issue 清单（Linear 首次导入用；之后以 Linear 为准） |
| [docs/roadmap/ROADMAP_platform.md](docs/roadmap/ROADMAP_platform.md) | 平台线：容器、AWS 基础设施、CI/CD、可观测性、安全 (中文) |
| [docs/roadmap/ROADMAP_data.md](docs/roadmap/ROADMAP_data.md) | 数据线：语料建设、ground truth dataset、数据源接入 (中文) |
| [docs/roadmap/ROADMAP_rag.md](docs/roadmap/ROADMAP_rag.md) | RAG 线：查询链路、评估工具、架构实验 (中文) |
| [docs/design/planned/eval-dataset.md](docs/design/planned/eval-dataset.md) | Ground truth dataset 怎么造：pooling / qrels / 难负例 / 标注 (中文) |
| [docs/design/planned/eval-experiments.md](docs/design/planned/eval-experiments.md) | 检索架构与模型实验矩阵 (中文) |
| [docs/design/chat-api-hardening.md](docs/design/implemented/chat-api-hardening.md) | `/chat` logging, security and rate limiting (中文) |
| [docs/design/storage-abstraction.md](docs/design/implemented/storage-abstraction.md) | Pipeline storage abstraction (中文) |
| [docs/design/deployment-packaging.md](docs/design/implemented/deployment-packaging.md) | Dependency locking and container images (中文) |
| [pipelines/README.md](pipelines/README.md) | Pipeline layout, local workflows, checkpoints |
| [docs/local-development.md](docs/local-development.md) | Local Docker workflows and command reference |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Branching, commits, PRs, versioning and releases |

---

## Team Structure

| Squad | Responsibilities |
|-------|-----------------|
| **A — Data** | Web scrapers, data cleaning, text chunking |
| **B — AI** | RAG pipeline, reranker, generator, prompt engineering |
| **C — Platform** | FastAPI layer, database, security, DevOps |

See [CONTRIBUTING.md](CONTRIBUTING.md) for branching, commit and release conventions (`feature/`, `fix/`, `hotfix/`, `chore/`, `dev/`).
