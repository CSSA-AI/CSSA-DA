from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pipelines.ingestion.wechat import WechatHarvesterConfig
from pipelines.orchestration.harvest_wechat import run_local_harvest
from pipelines.orchestration.import_knowledge_base import run_local_import
from pipelines.orchestration.transform_wechat import run_local_transform
from pipelines.shared.paths import DEFAULT_DATA_DIR


@dataclass(frozen=True)
class WechatPipelineRunResult:
    harvested_count: int
    transformed_count: int
    skipped_count: int
    dropped_count: int
    attempted_import_count: int
    inserted_count: int
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
    table_name: str | None = None,
    batch_size: int = 100,
) -> WechatPipelineRunResult:
    raw_output_file = data_dir / "wechat_articles_all.json"
    processed_output_file = (
        data_dir / "wechat_articles_processed.json"
    )

    harvest_result = run_local_harvest(
        config=harvester_config,
        data_dir=data_dir,
    )
    transform_result = run_local_transform(
        input_file=raw_output_file,
        output_file=processed_output_file,
        created_at=created_at,
    )
    import_result = run_local_import(
        database_url=database_url,
        input_file=processed_output_file,
        model_name=model_name,
        table_name=table_name,
        batch_size=batch_size,
    )

    return WechatPipelineRunResult(
        harvested_count=harvest_result.articles_written,
        transformed_count=transform_result.stats.output_count,
        skipped_count=transform_result.stats.skipped_count,
        dropped_count=transform_result.stats.dropped_count,
        attempted_import_count=import_result.attempted_count,
        inserted_count=import_result.inserted_count,
        raw_output_location=harvest_result.output_location,
        processed_output_file=processed_output_file,
    )
