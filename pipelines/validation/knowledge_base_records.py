from typing import Any


REQUIRED_FIELDS = (
    "question_text",
    "content",
    "source",
    "post_date",
    "language",
    "created_at",
    "tags",
    "link",
)


def validate_record(record: dict[str, Any], index: int) -> list[str]:
    errors = []

    for field in REQUIRED_FIELDS:
        if field not in record:
            errors.append(f"row {index}: missing {field}")

    # Strings, not merely truthy: the loader hands these to Postgres as they
    # are, and a bool, number or list is stored as its SQL text form ('true',
    # '1e+20', '{a,b}'), which no longer matches what the embedding was
    # computed from -- or what the import checks against after loading.
    for field in ("question_text", "content"):
        if field not in record:
            continue
        value = record[field]
        if not isinstance(value, str):
            errors.append(f"row {index}: {field} must be a string")
        elif not value:
            errors.append(f"row {index}: {field} is empty")

    if "link" in record:
        link = record["link"]
        if not isinstance(link, str) or not link.strip():
            errors.append(f"row {index}: link must be a non-empty string")

    if "tags" in record and not isinstance(record["tags"], list):
        errors.append(f"row {index}: tags must be a list")

    return errors


def validate_records(records: list[dict[str, Any]]) -> list[str]:
    errors = []
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            errors.append(f"row {index}: expected object")
            continue
        errors.extend(validate_record(record, index))
    return errors
