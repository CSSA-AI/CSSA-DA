import json
from typing import Any

from pipelines.shared.storage import Storage


def write_json_report(
    storage: Storage,
    key: str,
    payload: dict[str, Any],
) -> None:
    document = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    storage.write(key, f"{document}\n".encode("utf-8"))
