from datetime import datetime, timezone

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
    WECHAT_CHECKPOINT_KEY,
    WECHAT_RAW_CURRENT_KEY,
    WECHAT_RAW_DIR_KEY,
    WECHAT_TEMP_CHUNKS_PREFIX,
)
from pipelines.shared.storage import Storage


def build_wechat_raw_snapshot_key(
    *,
    run_started_at: datetime | None = None,
) -> str:
    run_started_at = run_started_at or datetime.now(timezone.utc)
    timestamp = (
        run_started_at.astimezone(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )
    return f"{WECHAT_RAW_DIR_KEY}/wechat_articles_{timestamp}.json"


def run_local_harvest(
    storage: Storage,
    *,
    config: WechatHarvesterConfig | None = None,
    run_started_at: datetime | None = None,
) -> HarvestResult:
    config = config or WechatHarvesterConfig.from_environment()
    checkpoint_store = JsonFileCheckpointStore(storage, WECHAT_CHECKPOINT_KEY)
    article_sink = JsonChunkArticleSink(
        storage,
        WECHAT_TEMP_CHUNKS_PREFIX,
        build_wechat_raw_snapshot_key(run_started_at=run_started_at),
        WECHAT_RAW_CURRENT_KEY,
    )

    return harvest_wechat(
        config=config,
        client=WechatClient(config),
        checkpoint_store=checkpoint_store,
        article_sink=article_sink,
    )
