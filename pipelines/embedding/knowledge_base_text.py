from typing import Any


def build_embedding_text(record: dict[str, Any]) -> str:
    question = record.get("question_text") or ""
    content = record.get("content") or ""
    return f"{question}\n\n{content}".strip()


def encode_records(
    records: list[dict[str, Any]],
    model,
) -> list[list[float]]:
    texts = [build_embedding_text(record) for record in records]
    embeddings = model.encode(texts, normalize_embeddings=True)
    return [embedding.tolist() for embedding in embeddings]
