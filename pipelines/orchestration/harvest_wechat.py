from datetime import datetime, timezone
from pathlib import Path

from pipelines.ingestion.wechat import (
    HarvestResult,
    WechatClient,
    WechatHarvesterConfig,
    harvest_wechat,
)
from pipelines.ingestion.wechat.storage import (
    JsonChunkArticleSink,
    JsonFileCheckpointStore,
)
from pipelines.shared.paths import (
    DEFAULT_CURRENT_DATA_DIR,
    DEFAULT_DATA_DIR,
    DEFAULT_WECHAT_CHECKPOINT_FILE,
    DEFAULT_WECHAT_RAW_DIR,
    DEFAULT_WECHAT_TEMP_CHUNKS_DIR,
)
from pipelines.shared.storage import LocalStorage


def build_wechat_raw_snapshot_file(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    run_started_at: datetime | None = None,
) -> Path:
    run_started_at = run_started_at or datetime.now(timezone.utc)
    timestamp = (
        run_started_at.astimezone(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )
    if data_dir == DEFAULT_DATA_DIR:
        return DEFAULT_WECHAT_RAW_DIR / f"wechat_articles_{timestamp}.json"
    return data_dir / "raw" / "wechat" / f"wechat_articles_{timestamp}.json"


def run_local_harvest(
    *,
    config: WechatHarvesterConfig | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
    run_started_at: datetime | None = None,
) -> HarvestResult:
    config = config or WechatHarvesterConfig.from_environment()
    current_file = (
        DEFAULT_CURRENT_DATA_DIR / "wechat_articles_all.json"
        if data_dir == DEFAULT_DATA_DIR
        else data_dir / "current" / "wechat_articles_all.json"
    )
    checkpoint_file = (
        DEFAULT_WECHAT_CHECKPOINT_FILE
        if data_dir == DEFAULT_DATA_DIR
        else data_dir / "checkpoints" / "wechat_scraper_state.json"
    )
    temp_chunks_dir = (
        DEFAULT_WECHAT_TEMP_CHUNKS_DIR
        if data_dir == DEFAULT_DATA_DIR
        else data_dir / "checkpoints" / "wechat_temp_chunks"
    )
    storage = LocalStorage(data_dir)
    checkpoint_store = JsonFileCheckpointStore(
        storage,
        checkpoint_file.relative_to(data_dir).as_posix(),
    )
    raw_snapshot_file = build_wechat_raw_snapshot_file(
        data_dir=data_dir,
        run_started_at=run_started_at,
    )
    article_sink = JsonChunkArticleSink(
        temp_dir=temp_chunks_dir,
        final_file=raw_snapshot_file,
        current_file=current_file,
    )

    return harvest_wechat(
        config=config,
        client=WechatClient(config),
        checkpoint_store=checkpoint_store,
        article_sink=article_sink,
    )
