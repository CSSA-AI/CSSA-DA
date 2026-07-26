import argparse

from pipelines.shared.json_records import load_json_records
from pipelines.shared.paths import (
    DEFAULT_DATA_DIR,
    DEFAULT_KNOWLEDGE_BASE_INPUT_KEY,
)
from pipelines.shared.storage import LocalStorage, Storage
from pipelines.validation.knowledge_base_records import validate_records


def dry_run(storage: Storage, key: str) -> int:
    records = load_json_records(storage, key)
    errors = validate_records(records)

    print(f"Input key: {key}")
    print(f"Rows found: {len(records)}")

    if errors:
        print(f"Invalid rows: {len(errors)}")
        for error in errors[:20]:
            print(f"- {error}")
        if len(errors) > 20:
            print(f"- ... {len(errors) - 20} more")
        return 1

    print("Valid rows: all")
    print("Dry run only: no embeddings generated and no database rows inserted.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate processed knowledge-base records before import."
    )
    parser.add_argument(
        "--input",
        default=DEFAULT_KNOWLEDGE_BASE_INPUT_KEY,
        help="Processed record key under the storage root.",
    )
    args = parser.parse_args()

    return dry_run(LocalStorage(DEFAULT_DATA_DIR), args.input)


if __name__ == "__main__":
    raise SystemExit(main())
