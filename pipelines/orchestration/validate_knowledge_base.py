import argparse
from pathlib import Path

from pipelines.shared.json_records import load_json_records
from pipelines.shared.paths import DEFAULT_KNOWLEDGE_BASE_INPUT
from pipelines.validation.knowledge_base_records import validate_records


def dry_run(input_file: Path) -> int:
    records = load_json_records(input_file)
    errors = validate_records(records)

    print(f"Input file: {input_file}")
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
        type=Path,
        default=DEFAULT_KNOWLEDGE_BASE_INPUT,
        help="Processed JSON file to validate.",
    )
    args = parser.parse_args()

    return dry_run(args.input)


if __name__ == "__main__":
    raise SystemExit(main())
