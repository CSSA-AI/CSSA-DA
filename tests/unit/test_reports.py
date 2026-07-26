import json
from pathlib import Path

from pipelines.shared.reports import write_json_report
from pipelines.shared.storage import LocalStorage


def test_write_json_report_stores_payload_under_key(tmp_path: Path):
    storage = LocalStorage(tmp_path)

    write_json_report(storage, "reports/pipelines/run.json", {"status": "ok"})

    assert json.loads(storage.read("reports/pipelines/run.json")) == {
        "status": "ok"
    }


def test_write_json_report_is_pretty_printed_with_trailing_newline(tmp_path: Path):
    storage = LocalStorage(tmp_path)

    write_json_report(storage, "reports/run.json", {"a": 1})

    assert storage.read("reports/run.json").decode("utf-8") == (
        "{\n"
        '  "a": 1\n'
        "}\n"
    )


def test_write_json_report_keeps_non_ascii_and_serializes_unknown_types(tmp_path: Path):
    from datetime import date

    storage = LocalStorage(tmp_path)

    write_json_report(
        storage,
        "reports/run.json",
        {"city": "墨尔本", "day": date(2026, 7, 24)},
    )

    document = storage.read("reports/run.json").decode("utf-8")
    assert "墨尔本" in document  # ensure_ascii=False keeps CJK readable
    assert "2026-07-24" in document  # default=str serializes date
