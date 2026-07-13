from dataclasses import dataclass
from typing import Any

import psycopg2

from app.core.config import settings
from app.services.readiness import ReadinessCheck, check_readiness


@dataclass(frozen=True)
class LatestPipelineRun:
    pipeline_name: str
    status: str
    started_at: str | None
    finished_at: str | None
    report_path: str | None
    error_type: str | None
    error_message: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_name": self.pipeline_name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "report_path": self.report_path,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


@dataclass(frozen=True)
class PipelineMetadataStatus:
    latest_run: LatestPipelineRun | None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.reason is None,
            "latest_run": (
                self.latest_run.to_dict() if self.latest_run else None
            ),
            **({"reason": self.reason} if self.reason else {}),
        }


@dataclass(frozen=True)
class SystemStatus:
    api: str
    rag_ready: bool
    readiness: ReadinessCheck
    pipeline_metadata: PipelineMetadataStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "api": self.api,
            "rag_ready": self.rag_ready,
            "readiness": self.readiness.to_dict(),
            "pipeline_metadata": self.pipeline_metadata.to_dict(),
        }


def get_system_status(
    database_url: str | None = None,
) -> SystemStatus:
    readiness = check_readiness(database_url)
    return SystemStatus(
        api="ok",
        rag_ready=readiness.is_ready,
        readiness=readiness,
        pipeline_metadata=get_pipeline_metadata_status(database_url),
    )


def get_pipeline_metadata_status(
    database_url: str | None = None,
    *,
    pipeline_name: str = "wechat",
) -> PipelineMetadataStatus:
    database_url = database_url or settings.DATABASE_URL
    if not database_url:
        return PipelineMetadataStatus(
            latest_run=None,
            reason="DATABASE_URL is not configured",
        )

    try:
        with psycopg2.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT to_regclass('pipeline_runs');
                    """
                )
                if cursor.fetchone()[0] is None:
                    return PipelineMetadataStatus(
                        latest_run=None,
                        reason="pipeline_runs table does not exist",
                    )

                cursor.execute(
                    """
                    SELECT pipeline_name, status, started_at, finished_at,
                           report_path, error_type, error_message
                    FROM pipeline_runs
                    WHERE pipeline_name = %s
                    ORDER BY started_at DESC
                    LIMIT 1;
                    """,
                    (pipeline_name,),
                )
                row = cursor.fetchone()
    except Exception as error:
        return PipelineMetadataStatus(
            latest_run=None,
            reason=str(error),
        )

    if row is None:
        return PipelineMetadataStatus(latest_run=None)

    return PipelineMetadataStatus(
        latest_run=LatestPipelineRun(
            pipeline_name=row[0],
            status=row[1],
            started_at=row[2].isoformat() if row[2] else None,
            finished_at=row[3].isoformat() if row[3] else None,
            report_path=row[4],
            error_type=row[5],
            error_message=row[6],
        )
    )
