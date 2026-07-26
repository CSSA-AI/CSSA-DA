import json
import shutil
from pathlib import Path

from pipelines.shared.json_records import load_json_records
from pipelines.shared.storage import LocalStorage
from pipelines.validation.knowledge_base_records import validate_records


def test_validate_records_accepts_processed_wechat_shape():
    temp_dir = Path(__file__).parent / ".tmp_validate_knowledge_base"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()

    try:
        input_file = temp_dir / "wechat_articles_processed.json"
        input_file.write_text(
            json.dumps(
                [
                    {
                        "question_text": "How do I apply?",
                        "content": "Apply through the student portal.",
                        "source": "WeChat: CSSA",
                        "author": None,
                        "post_date": "2026-04-10",
                        "language": "zh",
                        "created_at": "2026-06-30",
                        "tags": ["wechat", "CSSA"],
                        "link": "https://example.com/article",
                    }
                ]
            ),
            encoding="utf-8",
        )

        records = load_json_records(
            LocalStorage(temp_dir),
            "wechat_articles_processed.json",
        )

        assert validate_records(records) == []
    finally:
        shutil.rmtree(temp_dir)


def test_validate_records_rejects_old_questions_text_shape():
    errors = validate_records(
        [
            {
                "questions": ["How do I apply?"],
                "text": "Apply through the student portal.",
                "source": "WeChat: CSSA",
                "post_date": "2026-04-10",
                "language": "zh",
                "created_at": "2026-06-30",
                "tags": ["wechat", "CSSA"],
                "link": "https://example.com/article",
            }
        ]
    )

    assert "row 1: missing question_text" in errors
    assert "row 1: missing content" in errors


def test_validate_records_rejects_missing_null_and_blank_links():
    record = {
        "question_text": "How do I apply?",
        "content": "Apply through the student portal.",
        "source": "WeChat: CSSA",
        "post_date": "2026-04-10",
        "language": "zh",
        "created_at": "2026-06-30",
        "tags": ["wechat", "CSSA"],
    }

    errors = validate_records(
        [
            record,
            {**record, "link": None},
            {**record, "link": "   "},
        ]
    )

    assert "row 1: missing link" in errors
    assert "row 2: link must be a non-empty string" in errors
    assert "row 3: link must be a non-empty string" in errors
