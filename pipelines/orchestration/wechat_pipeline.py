import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pipelines.ingestion.wechat import WechatHarvesterConfig
from pipelines.orchestration.harvest_wechat import run_local_harvest
from pipelines.orchestration.import_knowledge_base import run_local_import
from pipelines.orchestration.transform_wechat import run_local_transform
from pipelines.shared.logging import pipeline_run_context
from pipelines.shared.paths import (
    DEFAULT_CURRENT_DATA_DIR,
    DEFAULT_DATA_DIR,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WechatPipelineRunResult:
    run_id: str
    harvested_count: int
    transformed_count: int
    skipped_count: int
    dropped_count: int
    attempted_import_count: int
    affected_count: int
    raw_output_location: str
    processed_output_file: Path

    @property
    def rejected_count(self) -> int:
        return self.skipped_count + self.dropped_count


def run_local_wechat_pipeline(
    database_url: str,
    *,
    harvester_config: WechatHarvesterConfig | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
    created_at: date | None = None,
    model_name: str | None = None,
    model_revision: str | None = None,
    table_name: str | None = None,
    batch_size: int = 100,
    import_checkpoint_file: Path | None = None,
    reset_import_checkpoint: bool = False,
    run_id: str | None = None,
) -> WechatPipelineRunResult:
    run_id = run_id or str(uuid4())
    run_started_at = datetime.now(timezone.utc)
    raw_output_file = data_dir / "wechat_articles_all.json"
    processed_output_file = data_dir / "wechat_articles_processed.json"
    if data_dir == DEFAULT_DATA_DIR:
        raw_output_file = (
            DEFAULT_CURRENT_DATA_DIR / "wechat_articles_all.json"
        )
        processed_output_file = (
            DEFAULT_CURRENT_DATA_DIR
            / "wechat_articles_processed.json"
        )
    else:
        raw_output_file = data_dir / "current" / "wechat_articles_all.json"
        processed_output_file = (
            data_dir / "current" / "wechat_articles_processed.json"
        )
    run_started = time.perf_counter()
    with pipeline_run_context(run_id):
        logger.info(
            "WeChat pipeline started",
            extra={"event": "pipeline_started"},
        )

        harvest_result = _run_stage(
            "harvest",
            lambda: run_local_harvest(
                config=harvester_config,
                data_dir=data_dir,
                run_started_at=run_started_at,
            ),
            lambda result: {
                "record_count": result.articles_written,
            },
        )
        transform_result = _run_stage(
            "transform",
            lambda: run_local_transform(
                input_file=raw_output_file,
                output_file=processed_output_file,
                data_dir=data_dir,
                created_at=created_at,
                run_started_at=run_started_at,
            ),
            lambda result: {
                "record_count": result.stats.output_count,
            },
        )
        import_result = _run_stage(
            "import",
            lambda: run_local_import(
                database_url=database_url,
                input_file=processed_output_file,
                model_name=model_name,
                model_revision=model_revision,
                table_name=table_name,
                batch_size=batch_size,
                checkpoint_file=import_checkpoint_file,
                reset_checkpoint=reset_import_checkpoint,
            ),
            lambda result: {
                "record_count": result.attempted_count,
                "affected_count": result.affected_count,
            },
        )

        result = WechatPipelineRunResult(
            run_id=run_id,
            harvested_count=harvest_result.articles_written,
            transformed_count=transform_result.stats.output_count,
            skipped_count=transform_result.stats.skipped_count,
            dropped_count=transform_result.stats.dropped_count,
            attempted_import_count=import_result.attempted_count,
            affected_count=import_result.affected_count,
            raw_output_location=harvest_result.output_location,
            processed_output_file=processed_output_file,
        )
        logger.info(
            "WeChat pipeline completed",
            extra={
                "event": "pipeline_completed",
                "duration_seconds": round(
                    time.perf_counter() - run_started,
                    6,
                ),
                "record_count": result.transformed_count,
                "affected_count": result.affected_count,
            },
        )
        return result


def _run_stage(
    stage: str,
    operation: Callable[[], Any],
    metrics: Callable[[Any], dict[str, Any]],
) -> Any:
    started = time.perf_counter()
    logger.info(
        "%s stage started",
        stage,
        extra={"event": "stage_started", "stage": stage},
    )

    try:
        result = operation()
    except Exception as error:
        logger.exception(
            "%s stage failed",
            stage,
            extra={
                "event": "stage_failed",
                "stage": stage,
                "duration_seconds": round(
                    time.perf_counter() - started,
                    6,
                ),
                "error_type": type(error).__name__,
            },
        )
        raise

    event_fields = {
        "event": "stage_completed",
        "stage": stage,
        "duration_seconds": round(
            time.perf_counter() - started,
            6,
        ),
    }
    event_fields.update(metrics(result))
    logger.info(
        "%s stage completed",
        stage,
        extra=event_fields,
    )
    return result
