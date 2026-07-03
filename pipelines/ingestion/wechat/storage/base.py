from typing import Any, Protocol

from pipelines.ingestion.wechat.models import ArticleOutput, HarvestState


class CheckpointStore(Protocol):
    def load(self) -> HarvestState: ...

    def save(self, state: HarvestState) -> None: ...

    def clear(self) -> None: ...


class ArticleSink(Protocol):
    def write_batch(
        self,
        batch_id: int,
        articles: list[dict[str, Any]],
    ) -> None: ...

    def finalize(self) -> ArticleOutput: ...
