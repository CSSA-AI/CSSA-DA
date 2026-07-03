import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipelines",
        description="Run CSSA data pipeline tasks.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "harvest-wechat",
        help="Harvest raw WeChat articles.",
    )
    commands.add_parser(
        "transform-wechat",
        help="Transform raw WeChat articles into knowledge-base records.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "harvest-wechat":
        from pipelines.orchestration.harvest_wechat import (
            run_local_harvest,
        )

        result = run_local_harvest()
        print(
            f"Harvested {result.articles_written} articles to "
            f"{result.output_location}"
        )
    elif args.command == "transform-wechat":
        from pipelines.orchestration.transform_wechat import (
            run_local_transform,
        )
        from pipelines.shared.paths import DEFAULT_KNOWLEDGE_BASE_INPUT

        result = run_local_transform()
        print(
            f"Transformed {result.stats.output_count} articles to "
            f"{DEFAULT_KNOWLEDGE_BASE_INPUT}"
        )

    return 0
