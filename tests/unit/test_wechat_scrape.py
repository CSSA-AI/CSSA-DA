import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from pipelines.ingestion.wechat import (
    HarvestState,
    WechatApiError,
    WechatClient,
    WechatHarvesterConfig,
    harvest_wechat,
)
from pipelines.ingestion.wechat.storage import (
    JsonChunkArticleSink,
    JsonFileCheckpointStore,
    MemoryArticleSink,
    MemoryCheckpointStore,
)
from pipelines.shared.storage import LocalStorage


@pytest.fixture
def config():
    return WechatHarvesterConfig(
        api_key="test-api-key",
        delay_seconds=0,
    )


@pytest.fixture
def test_workspace():
    workspace = Path(__file__).parent / ".tmp_wechat_scrape"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir()

    yield workspace

    if workspace.exists():
        shutil.rmtree(workspace)


def test_api_key_is_required(monkeypatch):
    monkeypatch.delenv("WECHAT_API_KEY", raising=False)

    with pytest.raises(ValueError, match="WECHAT_API_KEY is required"):
        WechatHarvesterConfig.from_environment()


def test_local_checkpoint_store_round_trip(test_workspace):
    store = JsonFileCheckpointStore(
        LocalStorage(test_workspace),
        "scraper_state.json",
    )
    state = HarvestState(
        begin=40,
        total_saved=35,
        valid_count=30,
        seen_links={"linkB", "linkA"},
    )

    store.save(state)

    assert store.load() == state
    assert not (test_workspace / "scraper_state.json.tmp").exists()

    store.clear()
    assert store.load() == HarvestState()


def test_local_article_sink_is_ordered_and_idempotent(test_workspace):
    sink = JsonChunkArticleSink(
        LocalStorage(test_workspace),
        "checkpoints/wechat_temp_chunks",
        "raw/wechat/wechat_articles_20260710T010203Z.json",
        "current/wechat_articles_all.json",
    )
    sink.write_batch(20, [{"title": "old second"}])
    sink.write_batch(0, [{"title": "first"}])
    sink.write_batch(20, [{"title": "second"}])

    output = sink.finalize()
    articles = json.loads(
        (
            test_workspace
            / "raw"
            / "wechat"
            / "wechat_articles_20260710T010203Z.json"
        ).read_text(encoding="utf-8")
    )
    current_articles = json.loads(
        (
            test_workspace
            / "current"
            / "wechat_articles_all.json"
        ).read_text(encoding="utf-8")
    )

    assert articles == [{"title": "first"}, {"title": "second"}]
    assert current_articles == articles
    assert output.article_count == 2
    assert output.location == "raw/wechat/wechat_articles_20260710T010203Z.json"
    assert not (test_workspace / "checkpoints" / "wechat_temp_chunks").exists()


def test_harvester_uses_injected_client_and_memory_storage(config):
    list_response = MagicMock()
    list_response.json.return_value = {
        "base_resp": {"ret": 0},
        "articles": [
            {
                "title": "测试文章",
                "link": "fake_url",
                "create_time": 123456789,
            }
        ],
    }
    empty_response = MagicMock()
    empty_response.json.return_value = {
        "base_resp": {"ret": 0},
        "articles": [],
    }
    http_client = MagicMock()
    http_client.get.side_effect = [
        list_response,
        requests.exceptions.Timeout(),
        empty_response,
    ]
    sleep = MagicMock()
    checkpoint_store = MemoryCheckpointStore()
    article_sink = MemoryArticleSink()

    result = harvest_wechat(
        config=config,
        client=WechatClient(config, http_client=http_client),
        checkpoint_store=checkpoint_store,
        article_sink=article_sink,
        sleep=sleep,
    )

    assert result.articles_written == 1
    assert article_sink.articles[0]["title"] == "测试文章"
    assert article_sink.articles[0]["content"] == ""
    assert checkpoint_store.load() == HarvestState()
    sleep.assert_called_once_with(0)
    assert all(
        call.kwargs["timeout"] == config.request_timeout_seconds
        for call in http_client.get.call_args_list
    )


def test_api_error_is_raised(config):
    response = MagicMock()
    response.json.return_value = {
        "base_resp": {
            "ret": 1,
            "err_msg": "expired credential",
        }
    }
    http_client = MagicMock()
    http_client.get.return_value = response

    with pytest.raises(WechatApiError, match="expired credential"):
        WechatClient(
            config,
            http_client=http_client,
        ).list_articles(0)


def test_keyboard_interrupt_is_propagated_without_advancing_state(config):
    client = MagicMock()
    client.list_articles.side_effect = KeyboardInterrupt
    checkpoint_store = MemoryCheckpointStore()

    with pytest.raises(KeyboardInterrupt):
        harvest_wechat(
            config=config,
            client=client,
            checkpoint_store=checkpoint_store,
            article_sink=MemoryArticleSink(),
            sleep=MagicMock(),
        )

    assert checkpoint_store.load() == HarvestState()


def test_failed_batch_write_does_not_advance_checkpoint(config):
    client = MagicMock()
    client.list_articles.return_value = [
        {
            "title": "测试文章",
            "link": "fake_url",
            "create_time": 123456789,
        }
    ]
    client.download_article.return_value = "valid article content " * 10
    checkpoint_store = MemoryCheckpointStore()
    article_sink = MagicMock()
    article_sink.write_batch.side_effect = OSError("storage unavailable")

    with pytest.raises(OSError, match="storage unavailable"):
        harvest_wechat(
            config=config,
            client=client,
            checkpoint_store=checkpoint_store,
            article_sink=article_sink,
            sleep=MagicMock(),
        )

    assert checkpoint_store.load() == HarvestState()
