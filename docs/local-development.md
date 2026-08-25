# Docker development guide

The Docker services start the FastAPI application automatically. Copy
`.env.example` to `.env` and set `OPENAI_API_KEY` before using `/v1/chat`.

## Start the API

```bash
docker compose --profile cpu up --build
```

Images are built from `Dockerfile.api` (the API service) and
`Dockerfile.pipeline` (pipeline tasks) — slim, multi-stage, uv-locked.

Open:

- API health: <http://localhost:8000/health>
- API readiness: <http://localhost:8000/ready>
- API/data status: <http://localhost:8000/status>
- Interactive API docs: <http://localhost:8000/docs>

The `cpu` profile runs the `migrate-cpu` service before starting the API, so
Alembic migrations are applied to PostgreSQL automatically. `/v1/chat` expects
`knowledge_base` rows to already exist; rebuild them with the pipeline commands
below when the database is empty or the processed data changes.

The pinned embedding and reranker models are baked into the image at build time
and preloaded on startup (`local_files_only`), so no model download happens on
the first `/v1/chat` request. Because preload blocks startup, once `/health`
responds the models are already loaded.

## Check configuration

Use this before starting a runtime profile or debugging missing environment
variables:

```bash
python ops/check_config.py --profile api
python ops/check_config.py --profile pipeline
python ops/check_config.py --profile harvester
python ops/check_config.py --profile all --json
```

The command reports whether required variables are configured without printing
secret values.

## Rebuild local knowledge base through Docker

Use this after changing pipeline code, processing new data, or resetting the
database volume:

```bash
# 1. Start Postgres and run migrations
docker compose --profile pipeline run --rm migrate-cpu

# 2. Rebuild processed records from local data
docker compose --profile pipeline run --rm --no-deps pipeline-cpu transform-wechat

# 3. Load records into PostgreSQL knowledge_base
docker compose --profile pipeline run --rm pipeline-cpu import-knowledge-base --reset-checkpoint

# 4. Smoke-test pgvector retrieval
#    (the pipeline image's entrypoint is `python -m pipelines`, so override it
#     with --entrypoint to run a different module)
docker compose --profile pipeline run --rm --entrypoint python pipeline-cpu \
  -m pipelines.orchestration.smoke_test_retrieval --query "墨尔本 校招"
```

Then start the API:

```bash
docker compose --profile cpu up --build
```

Smoke-test the running API:

```bash
python ops/smoke_test_api.py --message "墨尔本 校招"
```

Use `--health-only` when you only want to verify the server is reachable without
checking database readiness. Use `--ready-only` to check `/health` and `/ready`
without calling the RAG chain.

For a repeatable local production rehearsal, run:

```bash
python ops/rehearse_local_stack.py
```

By default this applies migrations, transforms local WeChat data, imports one
knowledge-base row, starts the API, then checks `/health` and `/ready`. Use
`--full-import` to import all rows, and `--include-chat` when you also want to
call `/v1/chat`.

The default rehearsal intentionally does not harvest from WeChat. It rebuilds
from existing raw data under `data/`, which makes the flow repeatable after the
short-lived WeChat credential expires. When you have a fresh manually collected
WeChat key and want to test source capture too, run:

```bash
WECHAT_API_KEY='<fresh-wechat-key>' python ops/rehearse_local_stack.py --include-ingestion
```

If `/ready` is not ready, inspect the database contents:

```bash
python ops/db_status.py
python ops/db_status.py --json
```

## Common commands

```bash
# Start in the background
docker compose --profile cpu up -d

# Follow API logs
docker compose logs -f api-cpu

# Open a shell
docker compose --profile cpu run --rm api-cpu bash

# Stop services while preserving database and model volumes
docker compose --profile cpu down
```

To rebuild after dependency or Dockerfile changes:

```bash
docker compose --profile cpu up --build --force-recreate
```

To remove persistent data and downloaded model caches as well:

```bash
docker compose --profile cpu down --volumes
```

## PostgreSQL

```bash
# Start only the local database
docker compose up -d postgres

# Apply database migrations through Docker
docker compose --profile pipeline run --rm migrate-cpu

# Inspect the database manually
docker exec -it rag_postgres_db psql -U rag_user -d rag_vectordb

# Backup local knowledge_base data
docker exec rag_postgres_db pg_dump -U rag_user -d rag_vectordb \
  --table=knowledge_base --data-only --column-inserts > knowledge_base_backup.sql
```

On Windows PowerShell, set `DATABASE_URL` like this:

```powershell
$env:DATABASE_URL='postgresql://rag_user:rag_password@localhost:5432/rag_vectordb'
.\.venv\Scripts\python.exe -m alembic upgrade head
```

For disposable local development data, reset the migrated schema with:

```powershell
$env:DATABASE_URL='postgresql://rag_user:rag_password@localhost:5432/rag_vectordb'
.\.venv\Scripts\python.exe -m alembic downgrade base
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Then seed the local database again from `/data`:

```powershell
.\.venv\Scripts\python.exe -m pipelines transform-wechat
.\.venv\Scripts\python.exe -m pipelines import-knowledge-base --reset-checkpoint
.\.venv\Scripts\python.exe ops\db_status.py
```

For a Docker-only reset, remove the local Postgres volume and rerun the
pipeline import:

```bash
docker compose --profile cpu down --volumes
docker compose --profile pipeline run --rm migrate-cpu
docker compose --profile pipeline run --rm pipeline-cpu import-knowledge-base --reset-checkpoint
```
