import json
from typing import Any

from pipelines.shared.storage import Storage


def load_json_records(storage: Storage, key: str) -> list[dict[str, Any]]:
    records = json.loads(storage.read(key))

    if not isinstance(records, list):
        raise ValueError(f"Expected a JSON list in {key}")

    return records


def write_json_records(
    storage: Storage,
    key: str,
    records: list[dict[str, Any]],
) -> None:
    document = json.dumps(records, ensure_ascii=False, indent=2)
    storage.write(key, document.encode("utf-8"))
