import argparse
import logging
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

DATABASE_URL_HELP = (
    "PostgreSQL URL. Defaults to DATABASE_URL (from the environment or "
    "./.env), else the URL assembled from DB_HOST/DB_PORT/DB_NAME/DB_USER/"
    "DB_PASSWORD (how ECS tasks are configured). The command_completed line "
    "logs which database was used, as target_id."
)


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
        default=None,
        help=DATABASE_URL_HELP,
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
        default=None,
        help=DATABASE_URL_HELP,
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
            database_target_id,
            run_local_import,
        )

        database_url = _database_url(parser, args)
        result = run_local_import(
            LocalStorage(DEFAULT_DATA_DIR),
            database_url=database_url,
            input_key=args.input,
            limit=args.limit,
            batch_size=args.batch_size,
            checkpoint_key=args.checkpoint_file,
            reset_checkpoint=args.reset_checkpoint,
            run_id=run_id,
        )
        # When the import runs in a container, the report file dies with it
        # and this line is the record that survives: corpus_sha256 goes into
        # the deployment as CORPUS_SHA256, and knowledge_base_rows is what
        # /ready must report afterwards.
        logger.info(
            "Knowledge-base import completed",
            extra={
                "event": "command_completed",
                "stage": args.command,
                "status": result.status,
                "limit": args.limit,
                "record_count": result.attempted_count,
                "unique_record_count": result.unique_record_count,
                "corpus_rows": result.corpus_rows,
                "affected_count": result.affected_count,
                "skipped_by_checkpoint": result.skipped_by_checkpoint,
                "corpus_sha256": result.corpus_sha256,
                "knowledge_base_rows": result.knowledge_base_rows,
                "rows_outside_corpus": result.rows_outside_corpus,
                "model_name": result.embedding_model,
                "model_revision": result.embedding_revision,
                "target_id": database_target_id(database_url),
                "report_key": result.report_key,
            },
        )
    elif args.command == "run-wechat-pipeline":
        from pipelines.loaders.postgres_pipeline_runs import (
            PostgresPipelineRunLoader,
        )
        from pipelines.orchestration.wechat_pipeline import (
            run_local_wechat_pipeline,
        )

        database_url = _database_url(parser, args)
        result = run_local_wechat_pipeline(
            LocalStorage(DEFAULT_DATA_DIR),
            database_url=database_url,
            batch_size=args.batch_size,
            reset_import_checkpoint=args.reset_import_checkpoint,
            pipeline_run_loader=PostgresPipelineRunLoader(database_url),
            run_id=run_id,
        )
        logger.info(
            "WeChat pipeline command completed",
            extra={
                "event": "command_completed",
                "stage": args.command,
                "record_count": result.transformed_count,
                "affected_count": result.affected_count,
                "corpus_sha256": result.corpus_sha256,
                "knowledge_base_rows": result.knowledge_base_rows,
                "skipped_by_checkpoint": result.import_skipped_by_checkpoint,
                "report_key": result.import_report_key,
            },
        )

    return 0


def _database_url(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> str:
    # Settings, not os.getenv: in an ECS task there is no DATABASE_URL, only
    # the DB_* parts Settings assembles it from (with the password
    # percent-encoded). Reading the environment directly here left the
    # import unable to find the database the migrations had just used.
    if args.database_url:
        return args.database_url
    from app.core.config import settings

    if not settings.DATABASE_URL:
        parser.error(
            "--database-url, DATABASE_URL, or DB_HOST/DB_NAME/DB_USER/"
            "DB_PASSWORD is required"
        )
    return settings.DATABASE_URL
