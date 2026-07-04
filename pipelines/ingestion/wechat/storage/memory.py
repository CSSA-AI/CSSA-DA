from copy import deepcopy
from typing import Any

from pipelines.ingestion.wechat.models import ArticleOutput, HarvestState


class MemoryCheckpointStore:
    def __init__(self):
        self._state = HarvestState()

    def load(self) -> HarvestState:
        return deepcopy(self._state)

    def save(self, state: HarvestState) -> None:
        self._state = deepcopy(state)

    def clear(self) -> None:
        self._state = HarvestState()


class MemoryArticleSink:
    def __init__(self):
        self._batches: dict[int, list[dict[str, Any]]] = {}
        self.articles: list[dict[str, Any]] = []

    def write_batch(
        self,
        batch_id: int,
        articles: list[dict[str, Any]],
    ) -> None:
        self._batches[batch_id] = deepcopy(articles)

    def finalize(self) -> ArticleOutput:
        self.articles = [
            article
            for batch_id in sorted(self._batches)
            for article in self._batches[batch_id]
        ]
        return ArticleOutput(
            location="memory://wechat-articles",
            article_count=len(self.articles),
        )
