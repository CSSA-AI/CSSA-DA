import shutil
from datetime import date
from pathlib import Path

from pipelines.shared.import_checkpoint import (
    ImportCheckpoint,
    ImportCheckpointIdentity,
    JsonImportCheckpointStore,
    build_import_checkpoint_identity,
    fingerprint_records,
)
from pipelines.shared.storage import LocalStorage


def _identity():
    return ImportCheckpointIdentity(
        dataset_fingerprint="abc123",
        model_name="test-model",
        table_name="knowledge_base",
        target_id="postgresql://localhost:5432/testdb",
        batch_size=100,
        record_count=10,
        model_revision="revision-123",
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
    store = JsonImportCheckpointStore(
        LocalStorage(temp_dir),
        "import_checkpoint.json",
    )
    checkpoint = ImportCheckpoint(
        identity=_identity(),
        next_batch_index=2,
        affected_count=200,
        status="failed",
        error="database unavailable",
    )

    try:
        store.save(checkpoint)

        assert store.load() == checkpoint
        assert not (temp_dir / "import_checkpoint.json.tmp").exists()

        store.clear()
        assert store.load() is None
    finally:
        shutil.rmtree(temp_dir)


def test_json_checkpoint_store_reads_legacy_inserted_count():
    temp_dir = Path(__file__).parent / ".tmp_import_checkpoint"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    checkpoint_file = temp_dir / "import_checkpoint.json"
    checkpoint_file.write_text(
        """
{
  "identity": {
    "dataset_fingerprint": "abc123",
    "model_name": "test-model",
    "table_name": "knowledge_base",
    "target_id": "postgresql://localhost:5432/testdb",
    "batch_size": 100,
    "record_count": 10,
    "model_revision": "revision-123"
  },
  "next_batch_index": 2,
  "inserted_count": 200,
  "status": "running",
  "error": null
}
""",
        encoding="utf-8",
    )
    store = JsonImportCheckpointStore(
        LocalStorage(temp_dir),
        "import_checkpoint.json",
    )

    try:
        checkpoint = store.load()

        assert checkpoint is not None
        assert checkpoint.affected_count == 200
    finally:
        shutil.rmtree(temp_dir)


def test_checkpoint_identity_changes_with_model_revision():
    records = [{"question_text": "What is CSSA?"}]
    common = {
        "records": records,
        "model_name": "embedding-model",
        "table_name": "knowledge_base",
        "target_id": "postgresql://localhost:5432/cssa",
        "batch_size": 100,
    }

    first = build_import_checkpoint_identity(
        **common,
        model_revision="revision-a",
    )
    second = build_import_checkpoint_identity(
        **common,
        model_revision="revision-b",
    )

    assert first != second
