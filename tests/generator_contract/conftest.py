from app.core.config import rag_config


def pytest_report_header(config):
    """Say which configuration the run tested, at the top of the output.

    The output is what gets pasted into a PR, and a bare "20 passed" does not
    say whether it was the old prompt or the new one. prompt_version() is the
    same fingerprint every chat_interactions row carries, so a pasted run can
    be matched against the production rows that prompt produced.
    """
    from app.services.chat_interactions import prompt_version

    generator = rag_config["generator"]
    context = generator.get("context", {})
    return (
        f"generator contract: model={generator['model_name']} "
        f"temperature={generator.get('temperature')} "
        f"prompt={prompt_version()} "
        f"context={context.get('max_items')}x{context.get('max_chars_per_item')} chars"
    )
