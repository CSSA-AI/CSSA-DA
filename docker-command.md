# Docker development guide

The Docker services start the FastAPI application automatically. Copy
`.env.example` to `.env` and set `OPENAI_API_KEY` before using `/chat`.

## Start the API

CPU:

```bash
docker compose --profile cpu up --build
```

NVIDIA GPU:

```bash
docker compose --profile gpu up --build
```

Open:

- API health: <http://localhost:8000/health>
- Interactive API docs: <http://localhost:8000/docs>

The `cpu` and `gpu` profiles run the `migrate-cpu` service before starting the
API, so Alembic migrations are applied to PostgreSQL automatically. `/chat`
expects `knowledge_base` rows to already exist; rebuild them with the pipeline
commands below when the database is empty or the processed data changes.

The first `/chat` request downloads the configured Hugging Face models. Docker
stores them in the `huggingface_cache` volume so later starts can reuse them.

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
docker compose --profile pipeline run --rm pipeline-cpu \
  python -m pipelines.orchestration.smoke_test_retrieval --query "墨尔本 校招"
```

Then start the API:

```bash
docker compose --profile cpu up --build
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
