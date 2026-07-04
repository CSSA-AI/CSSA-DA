from typing import Any, Protocol


class KnowledgeBaseLoader(Protocol):
    def insert_batch(
        self,
        records: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> int: ...
