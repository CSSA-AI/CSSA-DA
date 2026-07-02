from pipelines.embedding.knowledge_base_text import build_embedding_text


def test_build_embedding_text_combines_question_and_content():
    text = build_embedding_text(
        {
            "question_text": "How do I apply?",
            "content": "Apply through the student portal.",
        }
    )

    assert text == "How do I apply?\n\nApply through the student portal."
