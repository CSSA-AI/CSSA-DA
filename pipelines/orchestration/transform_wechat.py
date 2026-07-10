from datetime import date, datetime, timezone
from pathlib import Path

from pipelines.shared.json_records import (
    load_json_records,
    write_json_records,
)
from pipelines.shared.paths import (
    DEFAULT_DATA_DIR,
    DEFAULT_KNOWLEDGE_BASE_PROCESSED_DIR,
    DEFAULT_KNOWLEDGE_BASE_INPUT,
    DEFAULT_WECHAT_RAW_INPUT,
    LEGACY_WECHAT_RAW_INPUT,
)
from pipelines.transform.wechat_articles import (
    WechatTransformResult,
    transform_articles,
)


def build_knowledge_base_snapshot_file(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    run_started_at: datetime | None = None,
) -> Path:
    run_started_at = run_started_at or datetime.now(timezone.utc)
    timestamp = (
        run_started_at.astimezone(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )
    if data_dir == DEFAULT_DATA_DIR:
        return (
            DEFAULT_KNOWLEDGE_BASE_PROCESSED_DIR
            / f"wechat_articles_processed_{timestamp}.json"
        )
    return (
        data_dir
        / "processed"
        / "knowledge_base"
        / f"wechat_articles_processed_{timestamp}.json"
    )


def run_local_transform(
    *,
    input_file: Path = DEFAULT_WECHAT_RAW_INPUT,
    output_file: Path = DEFAULT_KNOWLEDGE_BASE_INPUT,
    snapshot_file: Path | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
    created_at: date | None = None,
    run_started_at: datetime | None = None,
) -> WechatTransformResult:
    if (
        input_file == DEFAULT_WECHAT_RAW_INPUT
        and not input_file.exists()
        and LEGACY_WECHAT_RAW_INPUT.exists()
    ):
        input_file = LEGACY_WECHAT_RAW_INPUT

    raw_articles = load_json_records(input_file)
    result = transform_articles(
        raw_articles,
        created_at=created_at or date.today(),
    )
    snapshot_file = snapshot_file or build_knowledge_base_snapshot_file(
        data_dir=data_dir,
        run_started_at=run_started_at,
    )
    write_json_records(snapshot_file, result.records)
    write_json_records(output_file, result.records)
    return result
