from dataclasses import dataclass
from datetime import datetime

import psycopg2


VALID_PIPELINE_RUN_STATUSES = {"started", "completed", "failed"}


@dataclass(frozen=True)
class PipelineRunRecord:
    id: str
    pipeline_name: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    input_path: str | None = None
    output_path: str | None = None
    report_path: str | None = None
    record_count: int | None = None
    affected_count: int | None = None
    error_type: str | None = None
    error_message: str | None = None


class PostgresPipelineRunLoader:
    def __init__(
        self,
        database_url: str,
        table_name: str = "pipeline_runs",
    ):
        if not database_url:
            raise ValueError("database_url is required")
        if table_name != "pipeline_runs":
            raise ValueError("only pipeline_runs table is supported")
        self.database_url = database_url
        self.table_name = table_name

    def upsert_run(self, record: PipelineRunRecord) -> int:
        _validate_record(record)
        with psycopg2.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO pipeline_runs (
                        id,
                        pipeline_name,
                        status,
                        started_at,
                        finished_at,
                        input_path,
                        output_path,
                        report_path,
                        record_count,
                        affected_count,
                        error_type,
                        error_message
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        pipeline_name = EXCLUDED.pipeline_name,
                        status = EXCLUDED.status,
                        started_at = EXCLUDED.started_at,
                        finished_at = EXCLUDED.finished_at,
                        input_path = EXCLUDED.input_path,
                        output_path = EXCLUDED.output_path,
                        report_path = EXCLUDED.report_path,
                        record_count = EXCLUDED.record_count,
                        affected_count = EXCLUDED.affected_count,
                        error_type = EXCLUDED.error_type,
                        error_message = EXCLUDED.error_message
                    """,
                    _record_to_row(record),
                )
                affected = cursor.rowcount
            connection.commit()
        return affected


def upsert_pipeline_run(
    database_url: str,
    record: PipelineRunRecord,
) -> int:
    return PostgresPipelineRunLoader(database_url).upsert_run(record)


def _validate_record(record: PipelineRunRecord) -> None:
    if not record.id.strip():
        raise ValueError("pipeline run id cannot be empty")
    if not record.pipeline_name.strip():
        raise ValueError("pipeline_name cannot be empty")
    if record.status not in VALID_PIPELINE_RUN_STATUSES:
        valid_statuses = ", ".join(sorted(VALID_PIPELINE_RUN_STATUSES))
        raise ValueError(f"status must be one of: {valid_statuses}")
    if (
        record.finished_at is not None
        and record.finished_at < record.started_at
    ):
        raise ValueError("finished_at cannot be before started_at")


def _record_to_row(record: PipelineRunRecord) -> tuple:
    return (
        record.id,
        record.pipeline_name,
        record.status,
        record.started_at,
        record.finished_at,
        record.input_path,
        record.output_path,
        record.report_path,
        record.record_count,
        record.affected_count,
        record.error_type,
        record.error_message,
    )
