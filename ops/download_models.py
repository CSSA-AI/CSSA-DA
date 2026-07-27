import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from huggingface_hub import snapshot_download

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import rag_config


IGNORED_MODEL_FILES = [
    "*.bin",
    "*.h5",
    "*.msgpack",
    "onnx/*",
    "openvino/*",
]


@dataclass(frozen=True)
class ModelDownload:
    name: str
    repo_id: str
    revision: str


MODEL_NAMES = ("embedding", "reranker")


def get_model_downloads(
    config: dict[str, Any],
    names: Sequence[str] | None = None,
) -> list[ModelDownload]:
    downloads = [
        ModelDownload(
            name="embedding",
            repo_id=config["retriever"]["embedding_model"],
            revision=config["retriever"].get("embedding_revision"),
        ),
        ModelDownload(
            name="reranker",
            repo_id=config["reranker"]["model_name"],
            revision=config["reranker"].get("model_revision"),
        ),
    ]

    if names is not None:
        unknown = set(names) - {model.name for model in downloads}
        if unknown:
            valid = ", ".join(sorted(m.name for m in downloads))
            raise ValueError(
                f"Unknown model(s): {', '.join(sorted(unknown))}. "
                f"Valid models: {valid}"
            )
        downloads = [model for model in downloads if model.name in names]

    for model in downloads:
        if not model.repo_id:
            raise ValueError(f"Model repository is required for {model.name}")
        if not model.revision:
            raise ValueError(f"Pinned model revision is required for {model.name}")

    return downloads


def download_models(
    target_dir: Path,
    config: dict[str, Any] = rag_config,
    names: Sequence[str] | None = None,
) -> list[Path]:
    target_dir = target_dir.resolve()
    downloaded_paths = []

    for model in get_model_downloads(config, names):
        local_dir = target_dir / model.name
        snapshot_download(
            repo_id=model.repo_id,
            revision=model.revision,
            local_dir=local_dir,
            ignore_patterns=IGNORED_MODEL_FILES,
        )
        downloaded_paths.append(local_dir)

    return downloaded_paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download pinned Hugging Face models from the RAG config."
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        required=True,
        help="Directory that will contain embedding and reranker models.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        choices=MODEL_NAMES,
        default=None,
        help=(
            "Which models to download. Defaults to all. The pipeline image "
            "only needs 'embedding'; the API image needs both."
        ),
    )
    args = parser.parse_args()

    for path in download_models(args.target_dir, names=args.models):
        print(f"Downloaded model to {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
