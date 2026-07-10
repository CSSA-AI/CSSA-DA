import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RehearsalOptions:
    import_limit: int | None = 1
    batch_size: int = 100
    reset_checkpoint: bool = True
    include_ingestion: bool = False
    include_chat: bool = False
    message: str = "墨尔本学校申请"
    base_url: str = "http://localhost:8000"


@dataclass(frozen=True)
class CommandStep:
    name: str
    command: list[str]


def build_rehearsal_steps(options: RehearsalOptions) -> list[CommandStep]:
    steps = [
        CommandStep(
            "Run PostgreSQL migrations",
            [
                "docker",
                "compose",
                "--profile",
                "pipeline",
                "run",
                "--rm",
                "migrate-cpu",
            ],
        ),
    ]
    if options.include_ingestion:
        steps.append(
            CommandStep(
                "Harvest WeChat raw data",
                [
                    "docker",
                    "compose",
                    "--profile",
                    "pipeline",
                    "run",
                    "--rm",
                    "--no-deps",
                    "pipeline-cpu",
                    "harvest-wechat",
                ],
            )
        )

    import_command = [
        "docker",
        "compose",
        "--profile",
        "pipeline",
        "run",
        "--rm",
        "pipeline-cpu",
        "import-knowledge-base",
        "--batch-size",
        str(options.batch_size),
    ]
    if options.import_limit is not None:
        import_command.extend(["--limit", str(options.import_limit)])
    if options.reset_checkpoint:
        import_command.append("--reset-checkpoint")

    smoke_command = [
        sys.executable,
        "ops/smoke_test_api.py",
        "--base-url",
        options.base_url,
        "--message",
        options.message,
    ]
    if not options.include_chat:
        smoke_command.append("--ready-only")

    steps.extend(
        [
        CommandStep(
            "Transform local WeChat data",
            [
                "docker",
                "compose",
                "--profile",
                "pipeline",
                "run",
                "--rm",
                "--no-deps",
                "pipeline-cpu",
                "transform-wechat",
            ],
        ),
        CommandStep(
            "Load knowledge_base rows",
            import_command,
        ),
        CommandStep(
            "Start API container",
            [
                "docker",
                "compose",
                "--profile",
                "cpu",
                "up",
                "-d",
                "--wait",
                "api-cpu",
            ],
        ),
        CommandStep(
            "Smoke-test API",
            smoke_command,
        ),
        ]
    )
    return steps


def run_steps(
    steps: Sequence[CommandStep],
    *,
    dry_run: bool = False,
) -> int:
    for step in steps:
        printable_command = " ".join(step.command)
        print(f"\n==> {step.name}")
        print(printable_command)
        if dry_run:
            continue

        completed = subprocess.run(step.command, cwd=PROJECT_ROOT)
        if completed.returncode != 0:
            print(f"Step failed: {step.name}")
            return completed.returncode

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rehearse the local Docker production flow: migrations, "
            "transform, import, API startup, and API smoke test."
        )
    )
    parser.add_argument(
        "--import-limit",
        type=int,
        default=1,
        help=(
            "Limit imported records for a quick rehearsal. Use "
            "--full-import if you want all records instead."
        ),
    )
    parser.add_argument(
        "--full-import",
        action="store_true",
        help="Import all processed records instead of a limited smoke import.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size passed to import-knowledge-base.",
    )
    parser.add_argument(
        "--keep-checkpoint",
        action="store_true",
        help="Reuse the existing import checkpoint instead of resetting it.",
    )
    parser.add_argument(
        "--include-ingestion",
        action="store_true",
        help=(
            "Harvest fresh WeChat raw data before transform. Requires a "
            "valid WECHAT_API_KEY because the source credential is manual "
            "and short-lived."
        ),
    )
    parser.add_argument(
        "--include-chat",
        action="store_true",
        help="Call /chat after /health and /ready. Requires OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--message",
        default="墨尔本学校申请",
        help="Message used when --include-chat is enabled.",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="API base URL for the smoke test.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the rehearsal commands without running them.",
    )
    args = parser.parse_args(argv)

    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than zero")
    if args.import_limit <= 0:
        parser.error("--import-limit must be greater than zero")

    options = RehearsalOptions(
        import_limit=None if args.full_import else args.import_limit,
        batch_size=args.batch_size,
        reset_checkpoint=not args.keep_checkpoint,
        include_ingestion=args.include_ingestion,
        include_chat=args.include_chat,
        message=args.message,
        base_url=args.base_url,
    )
    return run_steps(
        build_rehearsal_steps(options),
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
