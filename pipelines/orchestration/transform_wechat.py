from datetime import date, datetime, timezone

from pipelines.shared.json_records import (
    load_json_records,
    write_json_records,
)
from pipelines.shared.paths import (
    DEFAULT_KNOWLEDGE_BASE_INPUT_KEY,
    DEFAULT_WECHAT_RAW_INPUT_KEY,
    KNOWLEDGE_BASE_PROCESSED_DIR_KEY,
)
from pipelines.shared.storage import Storage
from pipelines.transform.wechat_articles import (
    WechatTransformResult,
    transform_articles,
)


def build_knowledge_base_snapshot_key(
    *,
    run_started_at: datetime | None = None,
) -> str:
    run_started_at = run_started_at or datetime.now(timezone.utc)
    timestamp = (
        run_started_at.astimezone(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )
    return (
        f"{KNOWLEDGE_BASE_PROCESSED_DIR_KEY}"
        f"/wechat_articles_processed_{timestamp}.json"
    )


def run_local_transform(
    storage: Storage,
    *,
    input_key: str = DEFAULT_WECHAT_RAW_INPUT_KEY,
    output_key: str = DEFAULT_KNOWLEDGE_BASE_INPUT_KEY,
    snapshot_key: str | None = None,
    created_at: date | None = None,
    run_started_at: datetime | None = None,
) -> WechatTransformResult:
    raw_articles = load_json_records(storage, input_key)
    result = transform_articles(
        raw_articles,
        created_at=created_at or date.today(),
    )
    snapshot_key = snapshot_key or build_knowledge_base_snapshot_key(
        run_started_at=run_started_at,
    )
    write_json_records(storage, snapshot_key, result.records)
    write_json_records(storage, output_key, result.records)
    return result
