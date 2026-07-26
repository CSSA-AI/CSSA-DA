import json
from typing import Any

from pipelines.ingestion.wechat.models import ArticleOutput, HarvestState
from pipelines.shared.storage import Storage


class JsonFileCheckpointStore:
    def __init__(self, storage: Storage, key: str):
        self.storage = storage
        self.key = key

    def load(self) -> HarvestState:
        if not self.storage.exists(self.key):
            return HarvestState()

        payload = json.loads(self.storage.read(self.key))

        return HarvestState(
            begin=payload.get("begin", 0),
            total_saved=payload.get("total_saved", 0),
            valid_count=payload.get("valid_count", 0),
            seen_links=set(payload.get("seen_links", [])),
        )

    def save(self, state: HarvestState) -> None:
        payload = {
            "begin": state.begin,
            "total_saved": state.total_saved,
            "valid_count": state.valid_count,
            "seen_links": sorted(state.seen_links),
        }
        document = json.dumps(payload, ensure_ascii=False, indent=2)
        self.storage.write(self.key, document.encode("utf-8"))

    def clear(self) -> None:
        self.storage.delete(self.key)


class JsonChunkArticleSink:
    def __init__(
        self,
        storage: Storage,
        temp_prefix: str,
        final_key: str,
        current_key: str | None = None,
    ):
        self.storage = storage
        self.temp_prefix = temp_prefix
        self.final_key = final_key
        self.current_key = current_key

    def write_batch(
        self,
        batch_id: int,
        articles: list[dict[str, Any]],
    ) -> None:
        document = json.dumps(articles, ensure_ascii=False, indent=2)
        self.storage.write(
            f"{self.temp_prefix}/batch_{batch_id}.json",
            document.encode("utf-8"),
        )

    def finalize(self) -> ArticleOutput:
        articles: list[dict[str, Any]] = []
        for key in sorted(self.storage.list(self.temp_prefix), key=_batch_offset):
            articles.extend(json.loads(self.storage.read(key)))

        document = json.dumps(
            articles, ensure_ascii=False, indent=2
        ).encode("utf-8")
        self.storage.write(self.final_key, document)

        if self.current_key is not None:
            self.storage.write(self.current_key, document)

        self.storage.delete_prefix(self.temp_prefix)

        return ArticleOutput(
            location=self.final_key,
            article_count=len(articles),
        )


def _batch_offset(key: str) -> int:
    stem = key.rsplit("/", 1)[-1].removesuffix(".json")
    return int(stem.removeprefix("batch_"))
