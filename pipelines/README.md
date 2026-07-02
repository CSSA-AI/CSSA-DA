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

## Knowledge base local workflow

From the repo root:

```powershell
# 1. Rebuild processed WeChat records from raw scraper output.
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pipelines.transform.wechat_articles

# 2. Validate records before import.
.\.venv\Scripts\python.exe -m pipelines.orchestration.validate_knowledge_base

# 3. Start local Postgres.
docker compose up -d postgres

# 4. Apply database migrations.
$env:DATABASE_URL='postgresql://rag_user:rag_password@localhost:5432/rag_vectordb'
.\.venv\Scripts\python.exe -m alembic upgrade head

# 5. Smoke-test one row first.
.\.venv\Scripts\python.exe -m pipelines.orchestration.import_knowledge_base --limit 1

# 6. Import all validated rows.
.\.venv\Scripts\python.exe -m pipelines.orchestration.import_knowledge_base

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
