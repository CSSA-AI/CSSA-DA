from unittest.mock import patch

from pipelines.cli import main


@patch("pipelines.ingestion.wechat_articles.fetch_pipeline")
def test_harvest_wechat_command(mock_fetch_pipeline):
    exit_code = main(["harvest-wechat"])

    assert exit_code == 0
    mock_fetch_pipeline.assert_called_once_with()


@patch(
    "pipelines.transform.wechat_articles.process_and_transform_articles"
)
def test_transform_wechat_command(mock_process_articles):
    exit_code = main(["transform-wechat"])

    assert exit_code == 0
    mock_process_articles.assert_called_once_with()
