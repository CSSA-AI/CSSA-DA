import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from pipelines.embedding.knowledge_base_text import build_embedding_text
from pipelines.orchestration.import_knowledge_base import (
    ImportResult,
    KnowledgeBaseValidationError,
    import_knowledge_base,
    run_local_import,
)


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
    loader.insert_batch.return_value = 1
    records = [_valid_record()]

    result = import_knowledge_base(
        records,
        embedder,
        loader,
    )

    assert result == ImportResult(attempted_count=1, inserted_count=1)
    embedder.encode.assert_called_once_with(
        [
            "How do I apply?\n\n"
            "Apply through the student portal."
        ],
        normalize_embeddings=True,
    )
    loader.insert_batch.assert_called_once_with(
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
    loader.insert_batch.assert_not_called()


def test_empty_import_avoids_embedding_and_database():
    embedder = MagicMock()
    loader = MagicMock()

    result = import_knowledge_base([], embedder, loader)

    assert result == ImportResult(attempted_count=0, inserted_count=0)
    embedder.encode.assert_not_called()
    loader.insert_batch.assert_not_called()


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
    loader.insert_batch.side_effect = [100, 100, 5]

    result = import_knowledge_base(
        records,
        embedder,
        loader,
        batch_size=100,
    )

    assert result == ImportResult(
        attempted_count=205,
        inserted_count=205,
    )
    assert [len(call.args[0]) for call in loader.insert_batch.call_args_list] == [
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
    loader.insert_batch.side_effect = [
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

    assert loader.insert_batch.call_count == 2
    assert embedder.encode.call_count == 2


def test_import_rejects_non_positive_batch_size():
    with pytest.raises(ValueError, match="batch_size"):
        import_knowledge_base(
            [],
            MagicMock(),
            MagicMock(),
            batch_size=0,
        )


@patch(
    "pipelines.orchestration.import_knowledge_base."
    "PostgresKnowledgeBaseLoader"
)
@patch("sentence_transformers.SentenceTransformer")
def test_local_import_loads_file_and_constructs_model(
    mock_sentence_transformer,
    mock_loader_class,
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
    loader.insert_batch.return_value = 1
    mock_loader_class.return_value.__enter__.return_value = loader

    try:
        result = run_local_import(
            DATABASE_URL,
            input_file=input_file,
            model_name="test-model",
        )
    finally:
        shutil.rmtree(temp_dir)

    assert result == ImportResult(attempted_count=1, inserted_count=1)
    mock_sentence_transformer.assert_called_once_with("test-model")
    mock_loader_class.assert_called_once_with(
        DATABASE_URL,
        "knowledge_base",
        expected_embedding_dim=384,
    )
    loader.insert_batch.assert_called_once()
