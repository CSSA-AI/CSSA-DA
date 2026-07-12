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

## Local data layout

Local pipeline artifacts use a layout that maps cleanly to object storage later:

```text
data/
  raw/          immutable source snapshots
  processed/    transformed pipeline outputs
  current/      stable inputs consumed by the next stage
  checkpoints/  resumable local pipeline state
  reports/      future run reports and audit summaries
```

This maps directly to future cloud paths such as `s3://bucket/raw/...`,
`s3://bucket/processed/...`, `s3://bucket/current/...`,
`s3://bucket/checkpoints/...` and `s3://bucket/reports/...`.

WeChat ingestion writes durable raw snapshots and updates a stable current file:

```text
data/raw/wechat/wechat_articles_<timestamp>.json
data/current/wechat_articles_all.json
data/checkpoints/wechat_scraper_state.json
```

The transform stage does the same for knowledge-base input:

```text
data/processed/knowledge_base/wechat_articles_processed_<timestamp>.json
data/current/wechat_articles_processed.json
data/checkpoints/import_knowledge_base.json
```

Pipeline commands read from `data/current` by default. This gives local
development a stable path while preserving timestamped source snapshots for
debugging, reruns and future S3-style storage. During migration, transform also
falls back to the legacy `data/wechat_articles_all.json` file if the new current
raw file does not exist.

Complete pipeline runs also write JSON reports:

```text
data/reports/pipelines/wechat_pipeline_<run_id>.json
```

Reports include the run status, start/end timestamps, source/output paths,
record counts and failure details when a stage raises an error. They are local
audit files today and map cleanly to future object-storage reports.

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
docker compose --profile pipeline run --rm migrate-cpu
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
the command; it resumes from the first unfinished batch without regenerating
earlier embeddings. All batches in one import run reuse a single PostgreSQL
connection.

Local progress is stored in `data/checkpoints/import_knowledge_base.json`. Its
identity includes the dataset fingerprint, embedding model and revision, table,
sanitized database target and batch size. A changed identity starts a new import
automatically. To deliberately rerun an unchanged completed import:

```powershell
.\.venv\Scripts\python.exe -m pipelines import-knowledge-base --reset-checkpoint
```

For the complete workflow, use `--reset-import-checkpoint`.

The embedding model revision is pinned in `app/core/config/rag-config.yaml` so
imports and retrieval use the same immutable model files. If that revision is
changed, reset the import checkpoint and rerun the import before serving
queries so existing rows are refreshed with the new embedding provenance.

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

# Or apply migrations through Docker.
docker compose --profile pipeline run --rm migrate-cpu

# 5. Smoke-test one row first.
.\.venv\Scripts\python.exe -m pipelines import-knowledge-base --limit 1

# 6. Import all validated rows.
.\.venv\Scripts\python.exe -m pipelines import-knowledge-base

# 7. Smoke-test retrieval from imported rows.
.\.venv\Scripts\python.exe -m pipelines.orchestration.smoke_test_retrieval --query "墨尔本 校招"
```

## Idempotency

Knowledge-base imports are idempotent by `(link, question_text)`.

Running the importer again skips unchanged rows, but updates existing rows when
source fields or embedding provenance changed:

```sql
ON CONFLICT (link, question_text) DO UPDATE ...
WHERE existing values are different from incoming values
```

The unique index is managed by Alembic migration
`20260630_0002_add_knowledge_base_dedupe_index.py`.
