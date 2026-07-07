from typing import Any, Protocol


class KnowledgeBaseLoader(Protocol):
    def load_batch(
        self,
        records: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> int: ...
