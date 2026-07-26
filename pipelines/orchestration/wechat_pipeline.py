import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from pipelines.ingestion.wechat import WechatHarvesterConfig
from pipelines.loaders.postgres_pipeline_runs import PipelineRunRecord
from pipelines.orchestration.harvest_wechat import run_local_harvest
from pipelines.orchestration.import_knowledge_base import run_local_import
from pipelines.orchestration.transform_wechat import run_local_transform
from pipelines.shared.logging import pipeline_run_context
from pipelines.shared.paths import (
    KNOWLEDGE_BASE_CURRENT_KEY,
    PIPELINE_REPORTS_PREFIX,
    WECHAT_RAW_CURRENT_KEY,
)
from pipelines.shared.reports import write_json_report
from pipelines.shared.storage import Storage


logger = logging.getLogger(__name__)


class PipelineRunMetadataLoader(Protocol):
    def upsert_run(self, record: PipelineRunRecord) -> int: ...


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
    processed_output_key: str
    report_key: str | None = None

    @property
    def rejected_count(self) -> int:
        return self.skipped_count + self.dropped_count


def run_local_wechat_pipeline(
    storage: Storage,
    database_url: str,
    *,
    harvester_config: WechatHarvesterConfig | None = None,
    created_at: date | None = None,
    model_name: str | None = None,
    model_revision: str | None = None,
    table_name: str | None = None,
    batch_size: int = 100,
    import_checkpoint_key: str | None = None,
    reset_import_checkpoint: bool = False,
    pipeline_run_loader: PipelineRunMetadataLoader | None = None,
    run_id: str | None = None,
) -> WechatPipelineRunResult:
    run_id = run_id or str(uuid4())
    run_started_at = datetime.now(timezone.utc)
    raw_output_key = WECHAT_RAW_CURRENT_KEY
    processed_output_key = KNOWLEDGE_BASE_CURRENT_KEY
    run_started = time.perf_counter()
    with pipeline_run_context(run_id):
        logger.info(
            "WeChat pipeline started",
            extra={"event": "pipeline_started"},
        )
        _upsert_pipeline_run_metadata(
            pipeline_run_loader,
            PipelineRunRecord(
                id=run_id,
                pipeline_name="wechat",
                status="started",
                started_at=run_started_at,
                input_path=raw_output_key,
            ),
        )

        try:
            harvest_result = _run_stage(
                "harvest",
                lambda: run_local_harvest(
                    storage,
                    config=harvester_config,
                    run_started_at=run_started_at,
                ),
                lambda result: {
                    "record_count": result.articles_written,
                },
            )
            transform_result = _run_stage(
                "transform",
                lambda: run_local_transform(
                    storage,
                    input_key=raw_output_key,
                    output_key=processed_output_key,
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
                    storage,
                    database_url,
                    input_key=processed_output_key,
                    model_name=model_name,
                    model_revision=model_revision,
                    table_name=table_name,
                    batch_size=batch_size,
                    checkpoint_key=import_checkpoint_key,
                    reset_checkpoint=reset_import_checkpoint,
                ),
                lambda result: {
                    "record_count": result.attempted_count,
                    "affected_count": result.affected_count,
                },
            )
        except Exception as error:
            finished_at = datetime.now(timezone.utc)
            report_key = _write_wechat_pipeline_report(
                storage=storage,
                run_id=run_id,
                status="failed",
                started_at=run_started_at,
                finished_at=finished_at,
                error=error,
            )
            _upsert_pipeline_run_metadata(
                pipeline_run_loader,
                PipelineRunRecord(
                    id=run_id,
                    pipeline_name="wechat",
                    status="failed",
                    started_at=run_started_at,
                    finished_at=finished_at,
                    input_path=raw_output_key,
                    output_path=processed_output_key,
                    report_path=report_key,
                    error_type=type(error).__name__,
                    error_message=str(error),
                ),
            )
            raise

        result = WechatPipelineRunResult(
            run_id=run_id,
            harvested_count=harvest_result.articles_written,
            transformed_count=transform_result.stats.output_count,
            skipped_count=transform_result.stats.skipped_count,
            dropped_count=transform_result.stats.dropped_count,
            attempted_import_count=import_result.attempted_count,
            affected_count=import_result.affected_count,
            raw_output_location=harvest_result.output_location,
            processed_output_key=processed_output_key,
        )
        finished_at = datetime.now(timezone.utc)
        report_key = _write_wechat_pipeline_report(
            storage=storage,
            run_id=run_id,
            status="completed",
            started_at=run_started_at,
            finished_at=finished_at,
            result=result,
        )
        result = replace(result, report_key=report_key)
        _upsert_pipeline_run_metadata(
            pipeline_run_loader,
            PipelineRunRecord(
                id=run_id,
                pipeline_name="wechat",
                status="completed",
                started_at=run_started_at,
                finished_at=finished_at,
                input_path=raw_output_key,
                output_path=processed_output_key,
                report_path=report_key,
                record_count=result.transformed_count,
                affected_count=result.affected_count,
            ),
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


def _upsert_pipeline_run_metadata(
    loader: PipelineRunMetadataLoader | None,
    record: PipelineRunRecord,
) -> None:
    if loader is None:
        return
    loader.upsert_run(record)


def _write_wechat_pipeline_report(
    *,
    storage: Storage,
    run_id: str,
    status: str,
    started_at: datetime,
    finished_at: datetime,
    result: WechatPipelineRunResult | None = None,
    error: Exception | None = None,
) -> str:
    report_key = f"{PIPELINE_REPORTS_PREFIX}/wechat_pipeline_{run_id}.json"
    payload: dict[str, Any] = {
        "run_id": run_id,
        "pipeline": "wechat",
        "status": status,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }
    if result is not None:
        payload.update(
            {
                "raw_output_location": result.raw_output_location,
                "processed_output_key": result.processed_output_key,
                "harvested_count": result.harvested_count,
                "transformed_count": result.transformed_count,
                "skipped_count": result.skipped_count,
                "dropped_count": result.dropped_count,
                "rejected_count": result.rejected_count,
                "attempted_import_count": result.attempted_import_count,
                "affected_count": result.affected_count,
            }
        )
    if error is not None:
        payload.update(
            {
                "error_type": type(error).__name__,
                "error_message": str(error),
            }
        )

    write_json_report(storage, report_key, payload)
    return report_key


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
