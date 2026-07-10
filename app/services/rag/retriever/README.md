# Retriever

The supported retriever is `PGVectorRetriever`.

It reads from the PostgreSQL `knowledge_base` table and uses pgvector distance
search. This keeps the API read path aligned with the data pipeline write path:

```text
pipelines import records -> PostgreSQL knowledge_base -> PGVectorRetriever
```

PostgreSQL is the source of truth for RAG retrieval. Local vector-index files are
not part of the supported application path.
