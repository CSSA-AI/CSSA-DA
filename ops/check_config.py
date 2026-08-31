import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import rag_config, settings


PROFILE_REQUIREMENTS = {
    "api": ("DATABASE_URL", "OPENAI_API_KEY", "CHAT_API_KEY"),
    "pipeline": ("DATABASE_URL",),
    "harvester": ("WECHAT_API_KEY",),
    "all": (
        "DATABASE_URL",
        "OPENAI_API_KEY",
        "CHAT_API_KEY",
        "WECHAT_API_KEY",
    ),
}


@dataclass(frozen=True)
class EnvVarStatus:
    name: str
    required: bool
    configured: bool


@dataclass(frozen=True)
class ConfigStatus:
    profile: str
    env: str
    ok: bool
    variables: list[EnvVarStatus]
    rag: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "variables": [asdict(variable) for variable in self.variables],
        }


def _env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return getattr(settings, name, None)
    return value


def check_config(profile: str = "all") -> ConfigStatus:
    if profile not in PROFILE_REQUIREMENTS:
        valid_profiles = ", ".join(sorted(PROFILE_REQUIREMENTS))
        raise ValueError(f"profile must be one of: {valid_profiles}")

    required_names = set(PROFILE_REQUIREMENTS[profile])
    known_names = (
        "ENV",
        "DATABASE_URL",
        "OPENAI_API_KEY",
        "CHAT_API_KEY",
        "WECHAT_API_KEY",
        # Never required, but worth seeing on a deploy: unset here means
        # every chat_interactions row written by this container carries a
        # null version coordinate.
        "GIT_SHA",
        "CORPUS_SHA256",
    )
    variables = [
        EnvVarStatus(
            name=name,
            required=name in required_names,
            configured=bool(_env_value(name)),
        )
        for name in known_names
    ]
    ok = all(
        variable.configured
        for variable in variables
        if variable.required
    )

    return ConfigStatus(
        profile=profile,
        env=_env_value("ENV") or "dev",
        ok=ok,
        variables=variables,
        rag={
            "embedding_model": rag_config["retriever"]["embedding_model"],
            "embedding_revision": rag_config["retriever"].get(
                "embedding_revision"
            ),
            "embedding_dim": rag_config["retriever"]["embedding_dim"],
            "pgvector_table": rag_config["pgvector"]["table_name"],
            "generator_model": rag_config["generator"]["model_name"],
            "reranker_model": rag_config["reranker"]["model_name"],
        },
    )


def print_human_status(status: ConfigStatus) -> None:
    print(f"Profile: {status.profile}")
    print(f"ENV: {status.env}")
    print(f"Status: {'ok' if status.ok else 'missing required config'}")
    print("Environment variables:")
    for variable in status.variables:
        required = "required" if variable.required else "optional"
        configured = "configured" if variable.configured else "missing"
        print(f"- {variable.name}: {configured} ({required})")

    print("RAG config:")
    for key, value in status.rag.items():
        print(f"- {key}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check runtime configuration without printing secrets."
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILE_REQUIREMENTS),
        default="all",
        help="Runtime profile to check.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    args = parser.parse_args()

    status = check_config(args.profile)
    if args.json:
        print(json.dumps(status.to_dict(), ensure_ascii=False, indent=2))
    else:
        print_human_status(status)

    return 0 if status.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
