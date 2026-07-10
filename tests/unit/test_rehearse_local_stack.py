import sys

from ops.rehearse_local_stack import (
    RehearsalOptions,
    build_rehearsal_steps,
    main,
)


def test_build_rehearsal_steps_defaults_to_quick_ready_check():
    steps = build_rehearsal_steps(RehearsalOptions())

    assert [step.name for step in steps] == [
        "Run PostgreSQL migrations",
        "Transform local WeChat data",
        "Load knowledge_base rows",
        "Start API container",
        "Smoke-test API",
    ]
    assert steps[2].command == [
        "docker",
        "compose",
        "--profile",
        "pipeline",
        "run",
        "--rm",
        "pipeline-cpu",
        "import-knowledge-base",
        "--batch-size",
        "100",
        "--limit",
        "1",
        "--reset-checkpoint",
    ]
    assert steps[4].command == [
        sys.executable,
        "ops/smoke_test_api.py",
        "--base-url",
        "http://localhost:8000",
        "--message",
        "墨尔本学校申请",
        "--ready-only",
    ]


def test_build_rehearsal_steps_can_run_full_import_and_chat():
    steps = build_rehearsal_steps(
        RehearsalOptions(
            import_limit=None,
            batch_size=25,
            reset_checkpoint=False,
            include_chat=True,
            message="hello",
            base_url="http://127.0.0.1:8000",
        )
    )

    assert steps[2].command == [
        "docker",
        "compose",
        "--profile",
        "pipeline",
        "run",
        "--rm",
        "pipeline-cpu",
        "import-knowledge-base",
        "--batch-size",
        "25",
    ]
    assert steps[4].command == [
        sys.executable,
        "ops/smoke_test_api.py",
        "--base-url",
        "http://127.0.0.1:8000",
        "--message",
        "hello",
    ]


def test_build_rehearsal_steps_can_include_manual_ingestion():
    steps = build_rehearsal_steps(
        RehearsalOptions(include_ingestion=True)
    )

    assert [step.name for step in steps] == [
        "Run PostgreSQL migrations",
        "Harvest WeChat raw data",
        "Transform local WeChat data",
        "Load knowledge_base rows",
        "Start API container",
        "Smoke-test API",
    ]
    assert steps[1].command == [
        "docker",
        "compose",
        "--profile",
        "pipeline",
        "run",
        "--rm",
        "--no-deps",
        "pipeline-cpu",
        "harvest-wechat",
    ]


def test_main_dry_run_does_not_execute_commands(capsys):
    exit_code = main(["--dry-run", "--import-limit", "2"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "import-knowledge-base" in captured.out
    assert "--limit 2" in captured.out
