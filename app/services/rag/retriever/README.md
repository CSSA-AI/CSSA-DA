# Retriever

The production/default retriever is `PGVectorRetriever`.

It reads from the PostgreSQL `knowledge_base` table and uses pgvector distance
search. This keeps the API read path aligned with the data pipeline write path:

```text
pipelines import records -> PostgreSQL knowledge_base -> PGVectorRetriever
```

`FAISSRetriever` remains in this package for legacy/demo experiments only. It
should not be used as the canonical application retriever because FAISS artifacts
are local files and can diverge from the database.
