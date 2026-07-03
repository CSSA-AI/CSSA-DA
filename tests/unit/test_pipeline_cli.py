from unittest.mock import patch

from pipelines.cli import main
from pipelines.ingestion.wechat import HarvestResult


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
    "pipelines.transform.wechat_articles.process_and_transform_articles"
)
def test_transform_wechat_command(mock_process_articles):
    exit_code = main(["transform-wechat"])

    assert exit_code == 0
    mock_process_articles.assert_called_once_with()
