import json
from pathlib import Path
from typing import Any


def load_json_records(input_file: Path) -> list[dict[str, Any]]:
    with input_file.open("r", encoding="utf-8") as file:
        records = json.load(file)

    if not isinstance(records, list):
        raise ValueError(f"Expected a JSON list in {input_file}")

    return records


def write_json_records(
    output_file: Path,
    records: list[dict[str, Any]],
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = output_file.with_suffix(f"{output_file.suffix}.tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)

    temporary_file.replace(output_file)
