# Reranker

The reranker re-scores candidate `SearchResult` objects returned by the
retriever.

It is intentionally independent of the retrieval backend:

```text
PGVectorRetriever -> candidate SearchResult list -> CrossEncoderReranker
```

The current implementation uses a CrossEncoder model and can optionally load a
LoRA adapter for domain-specific fine-tuning.
