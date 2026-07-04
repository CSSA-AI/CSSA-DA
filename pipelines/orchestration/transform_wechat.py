from datetime import date
from pathlib import Path

from pipelines.shared.json_records import (
    load_json_records,
    write_json_records,
)
from pipelines.shared.paths import (
    DEFAULT_KNOWLEDGE_BASE_INPUT,
    DEFAULT_WECHAT_RAW_INPUT,
)
from pipelines.transform.wechat_articles import (
    WechatTransformResult,
    transform_articles,
)


def run_local_transform(
    *,
    input_file: Path = DEFAULT_WECHAT_RAW_INPUT,
    output_file: Path = DEFAULT_KNOWLEDGE_BASE_INPUT,
    created_at: date | None = None,
) -> WechatTransformResult:
    raw_articles = load_json_records(input_file)
    result = transform_articles(
        raw_articles,
        created_at=created_at or date.today(),
    )
    write_json_records(output_file, result.records)
    return result
