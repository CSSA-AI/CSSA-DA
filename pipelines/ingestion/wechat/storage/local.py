import json
import shutil
from pathlib import Path
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
        temp_dir: Path,
        final_file: Path,
        current_file: Path | None = None,
    ):
        self.temp_dir = temp_dir
        self.final_file = final_file
        self.current_file = current_file

    def write_batch(
        self,
        batch_id: int,
        articles: list[dict[str, Any]],
    ) -> None:
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        batch_file = self.temp_dir / f"batch_{batch_id}.json"
        temporary_file = batch_file.with_suffix(".json.tmp")

        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(articles, file, ensure_ascii=False, indent=2)

        temporary_file.replace(batch_file)

    def finalize(self) -> ArticleOutput:
        articles: list[dict[str, Any]] = []
        batch_files = (
            list(self.temp_dir.glob("batch_*.json"))
            if self.temp_dir.exists()
            else []
        )

        for batch_file in sorted(batch_files, key=_batch_offset):
            with batch_file.open("r", encoding="utf-8") as file:
                articles.extend(json.load(file))

        self.final_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = self.final_file.with_suffix(
            f"{self.final_file.suffix}.tmp"
        )
        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(articles, file, ensure_ascii=False, indent=2)
        temporary_file.replace(self.final_file)

        if self.current_file is not None:
            self.current_file.parent.mkdir(parents=True, exist_ok=True)
            temporary_current_file = self.current_file.with_suffix(
                f"{self.current_file.suffix}.tmp"
            )
            shutil.copyfile(self.final_file, temporary_current_file)
            temporary_current_file.replace(self.current_file)

        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

        return ArticleOutput(
            location=str(self.final_file.resolve()),
            article_count=len(articles),
        )


def _batch_offset(batch_file: Path) -> int:
    return int(batch_file.stem.removeprefix("batch_"))
