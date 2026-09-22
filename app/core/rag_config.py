"""Reading rag-config.yaml.

There are two kinds of configuration in this project and they are not
interchangeable. `Settings` holds what differs between deployments --
credentials, the database address, log level -- and comes from the
environment. This file holds what is the same everywhere -- which models, which
revisions, embedding dimension, table name -- and is committed to the
repository, because changing it changes the product rather than the
environment.

They are kept separate for a reason worth remembering: if the embedding model
were an environment variable, someone could point production at a different
model without a commit, and the vectors already in `knowledge_base` would
silently stop meaning the same thing as the query vectors. Living in the repo
makes that change a pull request instead.

This loader sits outside `app.core.config` so that a caller who needs only the
YAML does not have to load the environment layer to reach it. Importing
`app.core.config` constructs `Settings`, reads `.env` and pulls in
pydantic-settings; the model download step in Dockerfile.api needs two strings
from this file and runs in a build stage where the application does not exist
yet. That is one reader, not a second one -- `app.core.config` re-exports what
is defined here, so the nineteen callers that say
`from app.core.config import rag_config` are reading exactly this dict, and any
validation added below applies to all of them.
"""

from pathlib import Path
from typing import Any

import yaml


CONFIG_DIR = Path(__file__).resolve().parent / "config"
RAG_CONFIG_PATH = CONFIG_DIR / "rag-config.yaml"


def load_yaml_config(path: Path = RAG_CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


rag_config = load_yaml_config()
