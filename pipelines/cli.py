import argparse
import os
from collections.abc import Sequence
from pathlib import Path

from pipelines.shared.paths import DEFAULT_KNOWLEDGE_BASE_INPUT


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipelines",
        description="Run CSSA data pipeline tasks.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "harvest-wechat",
        help="Harvest raw WeChat articles.",
    )
    commands.add_parser(
        "transform-wechat",
        help="Transform raw WeChat articles into knowledge-base records.",
    )
    import_command = commands.add_parser(
        "import-knowledge-base",
        help="Embed and import validated records into PostgreSQL.",
    )
    import_command.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_KNOWLEDGE_BASE_INPUT,
        help="Processed knowledge-base JSON file.",
    )
    import_command.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="PostgreSQL URL. Defaults to DATABASE_URL.",
    )
    import_command.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Import only the first N records.",
    )
    import_command.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of records to embed and insert per batch.",
    )
    pipeline_command = commands.add_parser(
        "run-wechat-pipeline",
        help=(
            "Harvest, transform, validate and import WeChat articles."
        ),
    )
    pipeline_command.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="PostgreSQL URL. Defaults to DATABASE_URL.",
    )
    pipeline_command.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of records to embed and insert per batch.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "harvest-wechat":
        from pipelines.orchestration.harvest_wechat import (
            run_local_harvest,
        )

        result = run_local_harvest()
        print(
            f"Harvested {result.articles_written} articles to "
            f"{result.output_location}"
        )
    elif args.command == "transform-wechat":
        from pipelines.orchestration.transform_wechat import (
            run_local_transform,
        )
        from pipelines.shared.paths import DEFAULT_KNOWLEDGE_BASE_INPUT

        result = run_local_transform()
        print(
            f"Transformed {result.stats.output_count} articles to "
            f"{DEFAULT_KNOWLEDGE_BASE_INPUT}"
        )
    elif args.command == "import-knowledge-base":
        from pipelines.orchestration.import_knowledge_base import (
            run_local_import,
        )

        if not args.database_url:
            parser.error(
                "--database-url or DATABASE_URL is required"
            )

        result = run_local_import(
            database_url=args.database_url,
            input_file=args.input,
            limit=args.limit,
            batch_size=args.batch_size,
        )
        print(
            f"Inserted {result.inserted_count} of "
            f"{result.attempted_count} records"
        )
    elif args.command == "run-wechat-pipeline":
        from pipelines.orchestration.wechat_pipeline import (
            run_local_wechat_pipeline,
        )

        if not args.database_url:
            parser.error(
                "--database-url or DATABASE_URL is required"
            )

        result = run_local_wechat_pipeline(
            database_url=args.database_url,
            batch_size=args.batch_size,
        )
        print(
            f"Harvested {result.harvested_count}, transformed "
            f"{result.transformed_count}, rejected "
            f"{result.rejected_count}, inserted "
            f"{result.inserted_count}"
        )

    return 0
