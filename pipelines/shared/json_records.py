import json
from pathlib import Path
from typing import Any


def load_json_records(input_file: Path) -> list[dict[str, Any]]:
    with input_file.open("r", encoding="utf-8") as file:
        records = json.load(file)

    if not isinstance(records, list):
        raise ValueError(f"Expected a JSON list in {input_file}")

    return records
