import json
import logging

from pipelines.shared.logging import (
    JsonLogFormatter,
    pipeline_run_context,
)


def test_json_formatter_includes_run_and_event_fields():
    record = logging.LogRecord(
        name="pipelines.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="batch complete",
        args=(),
        exc_info=None,
    )
    record.event = "batch_completed"
    record.stage = "import"
    record.batch_number = 2
    record.inserted_count = 100

    with pipeline_run_context("run-123"):
        payload = json.loads(JsonLogFormatter().format(record))

    assert payload["run_id"] == "run-123"
    assert payload["event"] == "batch_completed"
    assert payload["stage"] == "import"
    assert payload["batch_number"] == 2
    assert payload["inserted_count"] == 100
