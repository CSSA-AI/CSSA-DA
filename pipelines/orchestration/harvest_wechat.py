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
from pipelines.shared.paths import DEFAULT_DATA_DIR


def run_local_harvest(
    *,
    config: WechatHarvesterConfig | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> HarvestResult:
    config = config or WechatHarvesterConfig.from_environment()
    checkpoint_store = JsonFileCheckpointStore(
        data_dir / "scraper_state.json"
    )
    article_sink = JsonChunkArticleSink(
        temp_dir=data_dir / "temp_chunks",
        final_file=data_dir / "wechat_articles_all.json",
    )

    return harvest_wechat(
        config=config,
        client=WechatClient(config),
        checkpoint_store=checkpoint_store,
        article_sink=article_sink,
    )
