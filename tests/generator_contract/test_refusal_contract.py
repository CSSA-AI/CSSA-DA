"""The refusal contract, against the real model (ROADMAP_rag.md Phase 3.1).

rag-config.yaml's system prompt says: if the material does not contain the
answer, say so and do not make one up. The orchestrator has no code path
behind that sentence -- empty or irrelevant retrieval goes to the generator
unchanged -- so this is the only thing that notices when it stops being true.

Each case hands the production generator, bypassing retrieval, a context that
is relevant but lacks the answer, and requires both a refusal phrase and no
fact the context does not contain (app/services/rag/eval/refusal.py).

It calls OpenAI, so it does not run by default -- not in `pytest tests/unit`,
not in CI. Non-determinism, not cost, is the reason: a test that sometimes
fails gets skipped, and then it guards nothing. It runs instead at fixed
points (CONTRIBUTING.md, "Testing"):

    RUN_GENERATOR_CONTRACT=1 uv run pytest tests/generator_contract -v

A failure is a finding, not flakiness to retry past. And 20/20 does not mean
the hallucination rate is zero -- only that this configuration did not
obviously break the behaviour.
"""

import os

import pytest

from app.core.config import settings
from app.services.rag.eval.refusal import judge_refusal
from app.services.rag.generator.chatgpt_generator import ChatGPTGenerator
from tests.generator_contract.cases import evidence_for, load_cases

pytestmark = pytest.mark.generator_contract

if os.getenv("RUN_GENERATOR_CONTRACT") != "1":
    pytest.skip(
        "calls OpenAI for real; set RUN_GENERATOR_CONTRACT=1 to run it",
        allow_module_level=True,
    )

# Read at import, before any test runs: tests/conftest.py swaps OPENAI_API_KEY
# for a fake one around every test.
OPENAI_API_KEY = settings.OPENAI_API_KEY

CASES = load_cases()


@pytest.fixture(scope="module")
def generator():
    if not OPENAI_API_KEY:
        pytest.fail(
            "RUN_GENERATOR_CONTRACT=1 needs a real OPENAI_API_KEY in the "
            "environment or .env"
        )
    # Everything but the key comes from rag-config.yaml as production runs it,
    # temperature 0.3 included. Lowering it to make the run steadier would
    # test a configuration nobody is serving.
    return ChatGPTGenerator(api_key=OPENAI_API_KEY)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_refuses_and_invents_nothing(generator, case):
    results = case.search_results()

    answer = generator.generate_text(case.query, results)

    # _build_context is the exact string generate_text just sent, truncation
    # and all -- a fact cut off by max_chars_per_item was never available.
    evidence = evidence_for(case.query, generator._build_context(results))
    verdict = judge_refusal(answer, evidence=evidence, withheld=case.withheld)
    print(f"[{case.id}] {answer}")  # shown with -rA
    assert verdict.passed, (
        f"{verdict.explain()}\n\n"
        f"query:  {case.query}\n"
        f"answer: {answer}\n"
        f"case:   {case.why}"
    )
