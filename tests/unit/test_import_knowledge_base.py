import hashlib
import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from psycopg2.errors import UndefinedTable

from pipelines.embedding.knowledge_base_text import build_embedding_text
from pipelines.orchestration.import_knowledge_base import (
    ImportResult,
    KnowledgeBaseCounts,
    KnowledgeBaseImportIncompleteError,
    KnowledgeBaseValidationError,
    build_import_checkpoint_identity,
    count_knowledge_base_rows,
    database_target_id,
    import_knowledge_base,
    run_local_import,
)
from pipelines.shared.import_checkpoint import (
    MemoryImportCheckpointStore,
    fingerprint_records,
)
from pipelines.shared.storage import LocalStorage


DATABASE_URL = "postgresql://test:test@localhost:5432/testdb"


def _valid_record():
    return {
        "question_text": "How do I apply?",
        "content": "Apply through the student portal.",
        "source": "University",
        "author": None,
        "post_date": "2026-07-04",
        "language": "en",
        "created_at": "2026-07-04",
        "tags": ["application"],
        "link": "https://example.com/apply",
    }


def test_build_embedding_text_combines_question_and_content():
    text = build_embedding_text(_valid_record())

    assert text == (
        "How do I apply?\n\nApply through the student portal."
    )


def test_import_uses_injected_embedder():
    embedder = MagicMock()
    embedder.encode.return_value = np.array([[0.1] * 384])
    loader = MagicMock()
    loader.load_batch.return_value = 1
    records = [_valid_record()]

    result = import_knowledge_base(
        records,
        embedder,
        loader,
    )

    assert result == ImportResult(attempted_count=1, affected_count=1)
    embedder.encode.assert_called_once_with(
        [
            "How do I apply?\n\n"
            "Apply through the student portal."
        ],
        normalize_embeddings=True,
    )
    loader.load_batch.assert_called_once_with(
        records,
        [[0.1] * 384],
    )


def test_invalid_records_fail_before_embedding_or_loading():
    embedder = MagicMock()
    loader = MagicMock()

    with pytest.raises(KnowledgeBaseValidationError) as error:
        import_knowledge_base(
            [{"question_text": "", "content": ""}],
            embedder,
            loader,
        )

    assert error.value.errors
    embedder.encode.assert_not_called()
    loader.load_batch.assert_not_called()


def test_empty_import_avoids_embedding_and_database():
    embedder = MagicMock()
    loader = MagicMock()

    result = import_knowledge_base([], embedder, loader)

    assert result == ImportResult(attempted_count=0, affected_count=0)
    embedder.encode.assert_not_called()
    loader.load_batch.assert_not_called()


def test_import_processes_records_in_configured_batches():
    records = []
    for index in range(205):
        record = _valid_record()
        record["question_text"] = f"Question {index}"
        record["link"] = f"https://example.com/{index}"
        records.append(record)

    embedder = MagicMock()
    embedder.encode.side_effect = lambda texts, **_: np.array(
        [[0.1] * 384 for _ in texts]
    )
    loader = MagicMock()
    loader.load_batch.side_effect = [100, 100, 5]

    result = import_knowledge_base(
        records,
        embedder,
        loader,
        batch_size=100,
    )

    assert result == ImportResult(
        attempted_count=205,
        affected_count=205,
    )
    assert [len(call.args[0]) for call in loader.load_batch.call_args_list] == [
        100,
        100,
        5,
    ]
    assert embedder.encode.call_count == 3


def test_import_stops_after_failed_batch():
    records = []
    for index in range(3):
        record = _valid_record()
        record["question_text"] = f"Question {index}"
        record["link"] = f"https://example.com/{index}"
        records.append(record)

    embedder = MagicMock()
    embedder.encode.side_effect = lambda texts, **_: np.array(
        [[0.1] * 384 for _ in texts]
    )
    loader = MagicMock()
    loader.load_batch.side_effect = [
        2,
        OSError("database unavailable"),
    ]

    with pytest.raises(OSError, match="database unavailable"):
        import_knowledge_base(
            records,
            embedder,
            loader,
            batch_size=2,
        )

    assert loader.load_batch.call_count == 2
    assert embedder.encode.call_count == 2


def test_import_resumes_after_failed_batch_without_reembedding():
    records = []
    for index in range(3):
        record = _valid_record()
        record["question_text"] = f"Question {index}"
        record["link"] = f"https://example.com/{index}"
        records.append(record)

    identity = build_import_checkpoint_identity(
        records,
        model_name="test-model",
        table_name="knowledge_base",
        target_id=database_target_id(DATABASE_URL),
        batch_size=2,
    )
    checkpoint_store = MemoryImportCheckpointStore()
    first_embedder = MagicMock()
    first_embedder.encode.side_effect = lambda texts, **_: np.array(
        [[0.1] * 384 for _ in texts]
    )
    first_loader = MagicMock()
    first_loader.load_batch.side_effect = [
        2,
        OSError("database unavailable"),
    ]

    with pytest.raises(OSError, match="database unavailable"):
        import_knowledge_base(
            records,
            first_embedder,
            first_loader,
            batch_size=2,
            checkpoint_store=checkpoint_store,
            checkpoint_identity=identity,
        )

    failed_checkpoint = checkpoint_store.load()
    assert failed_checkpoint.status == "failed"
    assert failed_checkpoint.next_batch_index == 1
    assert failed_checkpoint.affected_count == 2

    resumed_embedder = MagicMock()
    resumed_embedder.encode.return_value = np.array([[0.1] * 384])
    resumed_loader = MagicMock()
    resumed_loader.load_batch.return_value = 1

    result = import_knowledge_base(
        records,
        resumed_embedder,
        resumed_loader,
        batch_size=2,
        checkpoint_store=checkpoint_store,
        checkpoint_identity=identity,
    )

    assert result == ImportResult(
        attempted_count=3,
        affected_count=3,
    )
    resumed_embedder.encode.assert_called_once()
    assert len(resumed_embedder.encode.call_args.args[0]) == 1
    resumed_loader.load_batch.assert_called_once()

    completed_embedder = MagicMock()
    completed_loader = MagicMock()
    cached_result = import_knowledge_base(
        records,
        completed_embedder,
        completed_loader,
        batch_size=2,
        checkpoint_store=checkpoint_store,
        checkpoint_identity=identity,
    )

    assert cached_result == result
    completed_embedder.encode.assert_not_called()
    completed_loader.load_batch.assert_not_called()


def test_changed_dataset_starts_a_new_checkpoint():
    first_records = [_valid_record()]
    store = MemoryImportCheckpointStore()
    first_identity = build_import_checkpoint_identity(
        first_records,
        model_name="test-model",
        table_name="knowledge_base",
        target_id=database_target_id(DATABASE_URL),
        batch_size=1,
    )
    first_embedder = MagicMock()
    first_embedder.encode.return_value = np.array([[0.1] * 384])
    first_loader = MagicMock()
    first_loader.load_batch.return_value = 1
    import_knowledge_base(
        first_records,
        first_embedder,
        first_loader,
        batch_size=1,
        checkpoint_store=store,
        checkpoint_identity=first_identity,
    )

    changed_record = _valid_record()
    changed_record["question_text"] = "A changed question"
    changed_record["link"] = "https://example.com/changed"
    changed_records = [changed_record]
    changed_identity = build_import_checkpoint_identity(
        changed_records,
        model_name="test-model",
        table_name="knowledge_base",
        target_id=database_target_id(DATABASE_URL),
        batch_size=1,
    )
    changed_embedder = MagicMock()
    changed_embedder.encode.return_value = np.array([[0.2] * 384])
    changed_loader = MagicMock()
    changed_loader.load_batch.return_value = 1

    result = import_knowledge_base(
        changed_records,
        changed_embedder,
        changed_loader,
        batch_size=1,
        checkpoint_store=store,
        checkpoint_identity=changed_identity,
    )

    assert result.affected_count == 1
    changed_embedder.encode.assert_called_once()
    changed_loader.load_batch.assert_called_once()
    assert store.load().identity == changed_identity


def test_import_rejects_non_positive_batch_size():
    with pytest.raises(ValueError, match="batch_size"):
        import_knowledge_base(
            [],
            MagicMock(),
            MagicMock(),
            batch_size=0,
        )


def _counts(knowledge_base_rows, corpus_rows=None):
    return KnowledgeBaseCounts(
        knowledge_base_rows=knowledge_base_rows,
        corpus_rows=(
            knowledge_base_rows if corpus_rows is None else corpus_rows
        ),
    )


@patch(
    "pipelines.orchestration.import_knowledge_base."
    "count_knowledge_base_rows",
    return_value=KnowledgeBaseCounts(knowledge_base_rows=1, corpus_rows=1),
)
@patch(
    "pipelines.orchestration.import_knowledge_base."
    "PostgresKnowledgeBaseLoader"
)
@patch("sentence_transformers.SentenceTransformer")
def test_local_import_loads_file_and_constructs_model(
    mock_sentence_transformer,
    mock_loader_class,
    _mock_count_rows,
):
    temp_dir = Path(__file__).parent / ".tmp_import_knowledge_base"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    input_file = temp_dir / "knowledge_base.json"
    input_file.write_text(
        json.dumps([_valid_record()]),
        encoding="utf-8",
    )
    model = MagicMock()
    model.encode.return_value = np.array([[0.1] * 384])
    mock_sentence_transformer.return_value = model
    loader = MagicMock()
    loader.load_batch.return_value = 1
    mock_loader_class.return_value.__enter__.return_value = loader

    storage = LocalStorage(temp_dir)
    try:
        result = run_local_import(
            storage,
            DATABASE_URL,
            input_key="knowledge_base.json",
            model_name="test-model",
            model_revision="revision-123",
        )
        cached_result = run_local_import(
            storage,
            DATABASE_URL,
            input_key="knowledge_base.json",
            model_name="test-model",
            model_revision="revision-123",
        )
    finally:
        shutil.rmtree(temp_dir)

    assert (result.attempted_count, result.affected_count) == (1, 1)
    assert result.skipped_by_checkpoint is False
    assert (
        cached_result.attempted_count,
        cached_result.affected_count,
    ) == (1, 1)
    assert cached_result.skipped_by_checkpoint is True
    mock_sentence_transformer.assert_called_once_with(
        "test-model",
        revision="revision-123",
    )
    mock_loader_class.assert_called_once_with(
        DATABASE_URL,
        "knowledge_base",
        embedding_model="test-model",
        embedding_revision="revision-123",
        expected_embedding_dim=384,
    )
    loader.load_batch.assert_called_once()


def _write_records(tmp_path, records):
    (tmp_path / "knowledge_base.json").write_text(
        json.dumps(records),
        encoding="utf-8",
    )
    return LocalStorage(tmp_path)


def _records(count):
    records = []
    for index in range(count):
        record = _valid_record()
        record["question_text"] = f"Question {index}"
        record["link"] = f"https://example.com/{index}"
        records.append(record)
    return records


def _md5(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _stub_embedding(mock_sentence_transformer, mock_loader_class):
    model = MagicMock()
    model.encode.side_effect = lambda texts, **_: np.array(
        [[0.1] * 384 for _ in texts]
    )
    mock_sentence_transformer.return_value = model
    loader = MagicMock()
    loader.load_batch.side_effect = lambda batch, _: len(batch)
    mock_loader_class.return_value.__enter__.return_value = loader
    return loader


@patch(
    "pipelines.orchestration.import_knowledge_base."
    "count_knowledge_base_rows"
)
@patch(
    "pipelines.orchestration.import_knowledge_base."
    "PostgresKnowledgeBaseLoader"
)
@patch("sentence_transformers.SentenceTransformer")
def test_local_import_records_corpus_sha256_and_verifies_by_key(
    mock_sentence_transformer,
    mock_loader_class,
    mock_count_rows,
    tmp_path,
):
    records = _records(3)
    storage = _write_records(tmp_path, records)
    _stub_embedding(mock_sentence_transformer, mock_loader_class)
    mock_count_rows.return_value = _counts(3)

    result = run_local_import(
        storage,
        "postgresql://importer:s3cret@db.internal:5432/rag_vectordb",
        input_key="knowledge_base.json",
        model_name="test-model",
        model_revision="revision-123",
        run_id="run-1",
    )

    report_key = "reports/pipelines/import_knowledge_base_run-1.json"
    report = json.loads(storage.read(report_key))
    assert result == ImportResult(
        attempted_count=3,
        affected_count=3,
        corpus_sha256=fingerprint_records(records),
        knowledge_base_rows=3,
        unique_record_count=3,
        rows_outside_corpus=0,
        skipped_by_checkpoint=False,
        report_key=report_key,
    )
    assert report["status"] == "completed"
    assert report["corpus_sha256"] == fingerprint_records(records)
    assert report["record_count"] == 3
    assert report["unique_record_count"] == 3
    assert report["corpus_rows"] == 3
    assert report["knowledge_base_rows"] == 3
    assert report["rows_outside_corpus"] == 0
    assert report["skipped_by_checkpoint"] is False
    assert report["limit"] is None
    assert report["embedding_model"] == "test-model"
    assert report["embedding_revision"] == "revision-123"
    assert set(report) >= {"started_at", "finished_at", "run_id"}
    # The report is a file people pass around; the password stays out of it.
    assert report["target_id"] == (
        "postgresql://db.internal:5432/rag_vectordb"
    )
    assert "s3cret" not in storage.read(report_key).decode("utf-8")
    # Every record is looked up by its key and the md5 of its content.
    mock_count_rows.assert_called_once_with(
        "postgresql://importer:s3cret@db.internal:5432/rag_vectordb",
        "knowledge_base",
        {
            (record["link"], record["question_text"]): _md5(record["content"])
            for record in records
        },
        embedding_model="test-model",
        embedding_revision="revision-123",
    )


@patch(
    "pipelines.orchestration.import_knowledge_base."
    "count_knowledge_base_rows",
    return_value=KnowledgeBaseCounts(knowledge_base_rows=2, corpus_rows=2),
)
@patch(
    "pipelines.orchestration.import_knowledge_base."
    "PostgresKnowledgeBaseLoader"
)
@patch("sentence_transformers.SentenceTransformer")
def test_corpus_sha256_covers_only_the_records_imported(
    mock_sentence_transformer,
    mock_loader_class,
    _mock_count_rows,
    tmp_path,
):
    records = _records(5)
    storage = _write_records(tmp_path, records)
    _stub_embedding(mock_sentence_transformer, mock_loader_class)

    result = run_local_import(
        storage,
        DATABASE_URL,
        input_key="knowledge_base.json",
        model_name="test-model",
        limit=2,
        run_id="run-1",
    )

    # Hashing the whole file would name a corpus the database does not hold.
    assert result.corpus_sha256 == fingerprint_records(records[:2])
    assert result.corpus_sha256 != fingerprint_records(records)
    assert json.loads(storage.read(result.report_key))["limit"] == 2


@patch(
    "pipelines.orchestration.import_knowledge_base."
    "count_knowledge_base_rows",
    return_value=KnowledgeBaseCounts(knowledge_base_rows=1, corpus_rows=1),
)
@patch(
    "pipelines.orchestration.import_knowledge_base."
    "PostgresKnowledgeBaseLoader"
)
@patch("sentence_transformers.SentenceTransformer")
def test_duplicate_keys_expect_one_row_with_the_last_content(
    mock_sentence_transformer,
    mock_loader_class,
    mock_count_rows,
    tmp_path,
):
    record = _valid_record()
    later = dict(record, content="A later, corrected answer.")
    storage = _write_records(tmp_path, [record, later])
    _stub_embedding(mock_sentence_transformer, mock_loader_class)

    result = run_local_import(
        storage,
        DATABASE_URL,
        input_key="knowledge_base.json",
        model_name="test-model",
        run_id="run-1",
    )

    report = json.loads(storage.read(result.report_key))
    assert report["record_count"] == 2
    assert report["unique_record_count"] == 1
    assert report["status"] == "completed"
    # The loader upserts in order, so the table ends up with the later one.
    corpus = mock_count_rows.call_args.args[2]
    assert corpus == {
        (record["link"], record["question_text"]): _md5(later["content"])
    }


@patch(
    "pipelines.orchestration.import_knowledge_base."
    "count_knowledge_base_rows"
)
@patch(
    "pipelines.orchestration.import_knowledge_base."
    "PostgresKnowledgeBaseLoader"
)
@patch("sentence_transformers.SentenceTransformer")
def test_completed_checkpoint_against_an_empty_table_fails_loudly(
    mock_sentence_transformer,
    mock_loader_class,
    mock_count_rows,
    tmp_path,
):
    records = _records(3)
    storage = _write_records(tmp_path, records)
    _stub_embedding(mock_sentence_transformer, mock_loader_class)
    mock_count_rows.return_value = _counts(3)
    run_local_import(
        storage,
        DATABASE_URL,
        input_key="knowledge_base.json",
        model_name="test-model",
        run_id="run-1",
    )

    # Same target id, but the database behind it was rebuilt (or this is a
    # different database reached on the same host:port/name). The checkpoint
    # still says "completed", so nothing is re-imported.
    mock_count_rows.return_value = _counts(0)
    with pytest.raises(KnowledgeBaseImportIncompleteError) as error:
        run_local_import(
            storage,
            DATABASE_URL,
            input_key="knowledge_base.json",
            model_name="test-model",
            run_id="run-2",
        )

    # Both commands that import name their own flag.
    assert "--reset-checkpoint" in str(error.value)
    assert "--reset-import-checkpoint" in str(error.value)
    report = json.loads(
        storage.read("reports/pipelines/import_knowledge_base_run-2.json")
    )
    assert report["status"] == "incomplete"
    assert report["skipped_by_checkpoint"] is True
    assert report["corpus_rows"] == 0
    assert report["unique_record_count"] == 3
    mock_sentence_transformer.assert_called_once()

    # The remedy the error names actually works: the import runs again.
    mock_count_rows.return_value = _counts(3)
    result = run_local_import(
        storage,
        DATABASE_URL,
        input_key="knowledge_base.json",
        model_name="test-model",
        reset_checkpoint=True,
        run_id="run-3",
    )

    assert result.knowledge_base_rows == 3
    assert result.skipped_by_checkpoint is False
    assert mock_sentence_transformer.call_count == 2


@patch(
    "pipelines.orchestration.import_knowledge_base."
    "count_knowledge_base_rows"
)
@patch(
    "pipelines.orchestration.import_knowledge_base."
    "PostgresKnowledgeBaseLoader"
)
@patch("sentence_transformers.SentenceTransformer")
def test_a_different_corpus_of_the_same_size_is_not_mistaken_for_this_one(
    mock_sentence_transformer,
    mock_loader_class,
    mock_count_rows,
    tmp_path,
):
    # The table holds as many active rows as this corpus has records -- but
    # they are another corpus (or another version of this one). Counting
    # rows alone would call that complete and hand out this corpus's hash.
    storage = _write_records(tmp_path, _records(3))
    _stub_embedding(mock_sentence_transformer, mock_loader_class)
    mock_count_rows.return_value = _counts(3, corpus_rows=0)

    with pytest.raises(KnowledgeBaseImportIncompleteError):
        run_local_import(
            storage,
            DATABASE_URL,
            input_key="knowledge_base.json",
            model_name="test-model",
            run_id="run-1",
        )


@patch(
    "pipelines.orchestration.import_knowledge_base."
    "count_knowledge_base_rows",
    return_value=KnowledgeBaseCounts(knowledge_base_rows=5, corpus_rows=3),
)
@patch(
    "pipelines.orchestration.import_knowledge_base."
    "PostgresKnowledgeBaseLoader"
)
@patch("sentence_transformers.SentenceTransformer")
def test_rows_outside_the_corpus_are_reported(
    mock_sentence_transformer,
    mock_loader_class,
    _mock_count_rows,
    tmp_path,
):
    storage = _write_records(tmp_path, _records(3))
    _stub_embedding(mock_sentence_transformer, mock_loader_class)

    with patch(
        "pipelines.orchestration.import_knowledge_base.logger"
    ) as import_logger:
        result = run_local_import(
            storage,
            DATABASE_URL,
            input_key="knowledge_base.json",
            model_name="test-model",
            run_id="run-1",
        )

    # Complete -- every record is there -- but /ready will count 5, and the
    # 2 extra rows are served too.
    assert result.rows_outside_corpus == 2
    assert result.knowledge_base_rows == 5
    report = json.loads(storage.read(result.report_key))
    assert report["status"] == "completed"
    assert report["rows_outside_corpus"] == 2
    warning = import_logger.warning.call_args
    assert warning.kwargs["extra"]["rows_outside_corpus"] == 2


@patch(
    "pipelines.orchestration.import_knowledge_base."
    "count_knowledge_base_rows",
    return_value=KnowledgeBaseCounts(knowledge_base_rows=0, corpus_rows=0),
)
def test_an_empty_import_names_no_corpus(_mock_count_rows, tmp_path):
    storage = _write_records(tmp_path, _records(3))

    result = run_local_import(
        storage,
        DATABASE_URL,
        input_key="knowledge_base.json",
        model_name="test-model",
        limit=0,
        run_id="run-1",
    )

    # A hash of an empty list must never become a deployment's CORPUS_SHA256.
    assert result.corpus_sha256 is None
    report = json.loads(storage.read(result.report_key))
    assert report["status"] == "empty"
    assert report["corpus_sha256"] is None


@patch("pipelines.orchestration.import_knowledge_base.psycopg2.connect")
def test_a_missing_table_says_to_migrate_first(mock_connect):
    cursor = mock_connect.return_value.cursor.return_value.__enter__
    cursor.return_value.execute.side_effect = UndefinedTable(
        'relation "knowledge_base" does not exist'
    )

    with pytest.raises(
        KnowledgeBaseImportIncompleteError,
        match="alembic upgrade head",
    ):
        count_knowledge_base_rows(
            DATABASE_URL,
            "knowledge_base",
            {("https://example.com/apply", "How do I apply?"): "abc"},
            embedding_model="test-model",
            embedding_revision=None,
        )

    mock_connect.return_value.close.assert_called_once()
