import argparse
import logging
import os
from collections.abc import Sequence
from uuid import uuid4

from pipelines.shared.logging import (
    configure_pipeline_logging,
    pipeline_run_context,
)
from pipelines.shared.paths import (
    DEFAULT_DATA_DIR,
    DEFAULT_KNOWLEDGE_BASE_INPUT_KEY,
)
from pipelines.shared.storage import LocalStorage


logger = logging.getLogger(__name__)


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
        default=DEFAULT_KNOWLEDGE_BASE_INPUT_KEY,
        help="Processed knowledge-base record key under the storage root.",
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
        help="Number of records to embed and load per batch.",
    )
    import_command.add_argument(
        "--checkpoint-file",
        default=None,
        help=(
            "Import checkpoint key under the storage root. Defaults to "
            "checkpoints/import_knowledge_base.json."
        ),
    )
    import_command.add_argument(
        "--reset-checkpoint",
        action="store_true",
        help="Discard prior import progress and start again.",
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
    pipeline_command.add_argument(
        "--reset-import-checkpoint",
        action="store_true",
        help="Discard prior import progress and start again.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_pipeline_logging()
    run_id = str(uuid4())

    with pipeline_run_context(run_id):
        logger.info(
            "Pipeline command started",
            extra={
                "event": "command_started",
                "stage": args.command,
            },
        )
        try:
            return _run_command(parser, args, run_id)
        except Exception as error:
            logger.exception(
                "Pipeline command failed",
                extra={
                    "event": "command_failed",
                    "stage": args.command,
                    "error_type": type(error).__name__,
                },
            )
            raise


def _run_command(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    run_id: str,
) -> int:
    if args.command == "harvest-wechat":
        from pipelines.orchestration.harvest_wechat import (
            run_local_harvest,
        )

        result = run_local_harvest(LocalStorage(DEFAULT_DATA_DIR))
        logger.info(
            "WeChat harvest completed",
            extra={
                "event": "command_completed",
                "stage": args.command,
                "record_count": result.articles_written,
            },
        )
    elif args.command == "transform-wechat":
        from pipelines.orchestration.transform_wechat import (
            run_local_transform,
        )

        result = run_local_transform(LocalStorage(DEFAULT_DATA_DIR))
        logger.info(
            "WeChat transformation completed",
            extra={
                "event": "command_completed",
                "stage": args.command,
                "record_count": result.stats.output_count,
            },
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
            LocalStorage(DEFAULT_DATA_DIR),
            database_url=args.database_url,
            input_key=args.input,
            limit=args.limit,
            batch_size=args.batch_size,
            checkpoint_key=args.checkpoint_file,
            reset_checkpoint=args.reset_checkpoint,
        )
        logger.info(
            "Knowledge-base import completed",
            extra={
                "event": "command_completed",
                "stage": args.command,
                "record_count": result.attempted_count,
                "affected_count": result.affected_count,
            },
        )
    elif args.command == "run-wechat-pipeline":
        from pipelines.loaders.postgres_pipeline_runs import (
            PostgresPipelineRunLoader,
        )
        from pipelines.orchestration.wechat_pipeline import (
            run_local_wechat_pipeline,
        )

        if not args.database_url:
            parser.error(
                "--database-url or DATABASE_URL is required"
            )

        result = run_local_wechat_pipeline(
            LocalStorage(DEFAULT_DATA_DIR),
            database_url=args.database_url,
            batch_size=args.batch_size,
            reset_import_checkpoint=args.reset_import_checkpoint,
            pipeline_run_loader=PostgresPipelineRunLoader(
                args.database_url
            ),
            run_id=run_id,
        )
        logger.info(
            "WeChat pipeline command completed",
            extra={
                "event": "command_completed",
                "stage": args.command,
                "record_count": result.transformed_count,
                "affected_count": result.affected_count,
            },
        )

    return 0
