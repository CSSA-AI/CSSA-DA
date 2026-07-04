import logging
import re
import time
from collections.abc import Callable
from datetime import datetime

from pipelines.ingestion.wechat.client import ArticleSourceClient
from pipelines.ingestion.wechat.models import (
    HarvestResult,
    HarvestState,
    WechatHarvesterConfig,
)
from pipelines.ingestion.wechat.storage.base import (
    ArticleSink,
    CheckpointStore,
)


logger = logging.getLogger(__name__)


def harvest_wechat(
    config: WechatHarvesterConfig,
    client: ArticleSourceClient,
    checkpoint_store: CheckpointStore,
    article_sink: ArticleSink,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> HarvestResult:
    state = checkpoint_store.load()

    while True:
        logger.info(
            "Fetching WeChat articles %s-%s",
            state.begin,
            state.begin + config.page_size,
        )
        articles = client.list_articles(state.begin)

        if not articles:
            return _finalize(state, checkpoint_store, article_sink)

        batch_results = []
        page_seen_links: set[str] = set()
        page_valid_count = 0

        for item in articles:
            title = item.get("title", "未命名文章")
            link = item.get("link")

            if (
                not link
                or link in state.seen_links
                or link in page_seen_links
            ):
                continue

            page_seen_links.add(link)

            try:
                content = client.download_article(link)
            except Exception as error:
                logger.warning(
                    "Failed to download WeChat article %s: %s",
                    title,
                    error,
                )
                content = ""

            pure_text = re.sub(
                r"[^\u4e00-\u9fa5a-zA-Z0-9]",
                "",
                content,
            )
            pure_length = len(pure_text)

            if len(content) > 3000 and pure_length < 50:
                logger.info("Dropping malformed WeChat article: %s", title)
                continue

            is_valid = pure_length >= 50
            if is_valid:
                page_valid_count += 1

            create_time = item.get("create_time", 0)
            formatted_date = (
                datetime.fromtimestamp(create_time).strftime("%Y-%m-%d")
                if create_time
                else "1970-01-01"
            )
            batch_results.append(
                {
                    "title": title,
                    "link": link,
                    "content": content,
                    "date": formatted_date,
                    "source": "WeChat",
                    "is_valid_for_rag": is_valid,
                }
            )
            sleep(config.delay_seconds)

        if not page_seen_links:
            return _finalize(state, checkpoint_store, article_sink)

        if batch_results:
            article_sink.write_batch(state.begin, batch_results)

        state = HarvestState(
            begin=state.begin + len(articles),
            total_saved=state.total_saved + len(batch_results),
            valid_count=state.valid_count + page_valid_count,
            seen_links=state.seen_links | page_seen_links,
        )
        checkpoint_store.save(state)


def _finalize(
    state: HarvestState,
    checkpoint_store: CheckpointStore,
    article_sink: ArticleSink,
) -> HarvestResult:
    output = article_sink.finalize()
    checkpoint_store.clear()

    return HarvestResult(
        output_location=output.location,
        articles_written=output.article_count,
        total_saved=state.total_saved,
        valid_count=state.valid_count,
    )
