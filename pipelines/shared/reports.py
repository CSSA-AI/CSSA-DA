import json
from pathlib import Path
from typing import Any


def write_json_report(
    report_file: Path,
    payload: dict[str, Any],
) -> Path:
    report_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = report_file.with_suffix(
        f"{report_file.suffix}.tmp"
    )

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2, default=str)
        file.write("\n")

    temporary_file.replace(report_file)
    return report_file
