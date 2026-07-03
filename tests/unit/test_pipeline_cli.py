from unittest.mock import patch

from pipelines.cli import main
from pipelines.ingestion.wechat import HarvestResult
from pipelines.transform.wechat_articles import (
    WechatTransformResult,
    WechatTransformStats,
)


@patch("pipelines.orchestration.harvest_wechat.run_local_harvest")
def test_harvest_wechat_command(mock_run_local_harvest):
    mock_run_local_harvest.return_value = HarvestResult(
        output_location="data/wechat_articles_all.json",
        articles_written=10,
        total_saved=10,
        valid_count=8,
    )

    exit_code = main(["harvest-wechat"])

    assert exit_code == 0
    mock_run_local_harvest.assert_called_once_with()


@patch(
    "pipelines.orchestration.transform_wechat.run_local_transform"
)
def test_transform_wechat_command(mock_process_articles):
    mock_process_articles.return_value = WechatTransformResult(
        records=[],
        stats=WechatTransformStats(
            input_count=0,
            skipped_count=0,
            dropped_count=0,
            output_count=0,
            original_char_count=0,
            cleaned_char_count=0,
        ),
    )

    exit_code = main(["transform-wechat"])

    assert exit_code == 0
    mock_process_articles.assert_called_once_with()
