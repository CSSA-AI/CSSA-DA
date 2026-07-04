# Data pipelines

This package contains production-oriented data pipeline code.

## Layout

```text
pipelines/
  ingestion/      Raw data ingestion from external systems
  transform/      Source-specific normalization and cleaning
  validation/     Data contract checks before expensive work
  chunking/       Content chunking strategies
  embedding/      Embedding text construction and vector generation
  loaders/        Load targets, such as Postgres `knowledge_base`
  orchestration/  Runnable pipeline jobs / CLI entrypoints
  shared/         Shared paths, JSON IO, and generic utilities
```

Source-specific transforms live separately from load targets. The WeChat cleaning
step is implemented in:

```text
pipelines/transform/wechat_articles.py
```

## Complete local workflow

To run harvesting, transformation, validation, embedding and import as one
fail-fast workflow:

```powershell
$env:WECHAT_API_KEY='<wechat-api-key>'
$env:DATABASE_URL='postgresql://rag_user:rag_password@localhost:5432/rag_vectordb'
.\.venv\Scripts\python.exe -m pipelines run-wechat-pipeline
```

The individual stage commands remain available for development and recovery.

### Run through Docker

The pipeline service uses the CPU image, local `data/` directory, shared model
cache and Docker PostgreSQL network:

```powershell
$env:WECHAT_API_KEY='<wechat-api-key>'
docker compose --profile pipeline run --rm --entrypoint alembic pipeline-cpu upgrade head
docker compose --profile pipeline run --rm pipeline-cpu run-wechat-pipeline
```

Individual commands use the same service:

```powershell
docker compose --profile pipeline run --rm --no-deps pipeline-cpu transform-wechat
docker compose --profile pipeline run --rm pipeline-cpu import-knowledge-base
```

## Observability

Pipeline commands emit JSON logs to standard output. Every command receives a
`run_id`; the complete workflow also logs stage duration, record counts,
failures and import batch progress. Docker captures these logs directly, and
the same JSON format can later be sent to CloudWatch.

## Import batching

Knowledge-base imports validate the complete input before embedding, then process
records in batches of 100 by default:

```powershell
.\.venv\Scripts\python.exe -m pipelines import-knowledge-base --batch-size 250
```

Each completed batch is committed independently. If a later batch fails, rerun
the command; the database uniqueness constraint skips records already inserted.
All batches in one import run reuse a single PostgreSQL connection.

## Knowledge base local workflow

From the repo root:

```powershell
# 1. Rebuild processed WeChat records from raw scraper output.
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pipelines transform-wechat

# 2. Validate records before import.
.\.venv\Scripts\python.exe -m pipelines.orchestration.validate_knowledge_base

# 3. Start local Postgres.
docker compose up -d postgres

# 4. Apply database migrations.
$env:DATABASE_URL='postgresql://rag_user:rag_password@localhost:5432/rag_vectordb'
.\.venv\Scripts\python.exe -m alembic upgrade head

# 5. Smoke-test one row first.
.\.venv\Scripts\python.exe -m pipelines import-knowledge-base --limit 1

# 6. Import all validated rows.
.\.venv\Scripts\python.exe -m pipelines import-knowledge-base

# 7. Smoke-test retrieval from imported rows.
.\.venv\Scripts\python.exe -m pipelines.orchestration.smoke_test_retrieval --query "墨尔本 校招"
```

## Idempotency

Knowledge-base imports are idempotent by `(link, question_text)`.

Running the importer again skips rows that already exist:

```sql
ON CONFLICT (link, question_text) DO NOTHING
```

The unique index is managed by Alembic migration
`20260630_0002_add_knowledge_base_dedupe_index.py`.
