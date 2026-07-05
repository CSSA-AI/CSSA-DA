import shutil
from datetime import date
from pathlib import Path

from pipelines.shared.import_checkpoint import (
    ImportCheckpoint,
    ImportCheckpointIdentity,
    JsonImportCheckpointStore,
    fingerprint_records,
)


def _identity():
    return ImportCheckpointIdentity(
        dataset_fingerprint="abc123",
        model_name="test-model",
        table_name="knowledge_base",
        target_id="postgresql://localhost:5432/testdb",
        batch_size=100,
        record_count=10,
    )


def test_record_fingerprint_is_deterministic():
    first = [
        {
            "question_text": "Question",
            "post_date": date(2026, 7, 4),
            "tags": ["one", "two"],
        }
    ]
    same_with_different_key_order = [
        {
            "tags": ["one", "two"],
            "post_date": date(2026, 7, 4),
            "question_text": "Question",
        }
    ]
    changed = [{**first[0], "question_text": "Changed"}]

    assert fingerprint_records(first) == fingerprint_records(
        same_with_different_key_order
    )
    assert fingerprint_records(first) != fingerprint_records(changed)


def test_json_checkpoint_store_round_trip():
    temp_dir = Path(__file__).parent / ".tmp_import_checkpoint"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    checkpoint_file = temp_dir / "import_checkpoint.json"
    store = JsonImportCheckpointStore(checkpoint_file)
    checkpoint = ImportCheckpoint(
        identity=_identity(),
        next_batch_index=2,
        inserted_count=200,
        status="failed",
        error="database unavailable",
    )

    try:
        store.save(checkpoint)

        assert store.load() == checkpoint
        assert not checkpoint_file.with_suffix(".json.tmp").exists()

        store.clear()
        assert store.load() is None
    finally:
        shutil.rmtree(temp_dir)
