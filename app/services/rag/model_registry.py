from dataclasses import dataclass
from threading import Lock
from typing import Literal

from peft import PeftModel
from sentence_transformers import CrossEncoder, SentenceTransformer

from app.core.config import rag_config, settings


ModelLoadState = Literal["not_loaded", "loading", "ready", "failed"]


class ModelPreloadError(RuntimeError):
    """Raised when one or more configured models fail to preload."""


@dataclass(frozen=True)
class ModelRegistryStatus:
    embedding: ModelLoadState
    reranker: ModelLoadState

    @property
    def state(self) -> ModelLoadState:
        states = (self.embedding, self.reranker)
        if all(state == "ready" for state in states):
            return "ready"
        if "failed" in states:
            return "failed"
        if "loading" in states:
            return "loading"
        return "not_loaded"

    @property
    def is_ready(self) -> bool:
        return self.state == "ready"

    def to_dict(self) -> dict[str, str]:
        return {
            "status": self.state,
            "embedding": self.embedding,
            "reranker": self.reranker,
        }


class ModelRegistry:
    """Load and share the configured embedding and reranker models."""

    def __init__(self) -> None:
        self._embedding_model: SentenceTransformer | None = None
        self._reranker_model: CrossEncoder | None = None
        self._embedding_lock = Lock()
        self._reranker_lock = Lock()
        self._embedding_state: ModelLoadState = "not_loaded"
        self._reranker_state: ModelLoadState = "not_loaded"

    def get_embedding_model(self) -> SentenceTransformer:
        if self._embedding_model is None:
            with self._embedding_lock:
                if self._embedding_model is None:
                    self._embedding_state = "loading"
                    try:
                        self._embedding_model = self._load_embedding_model()
                    except Exception:
                        self._embedding_state = "failed"
                        raise
                    self._embedding_state = "ready"
        return self._embedding_model

    def get_reranker_model(self) -> CrossEncoder:
        if self._reranker_model is None:
            with self._reranker_lock:
                if self._reranker_model is None:
                    self._reranker_state = "loading"
                    try:
                        self._reranker_model = self._load_reranker_model()
                    except Exception:
                        self._reranker_state = "failed"
                        raise
                    self._reranker_state = "ready"
        return self._reranker_model

    def preload_models(self) -> None:
        errors = []
        try:
            embedding_model = self.get_embedding_model()
            if hasattr(embedding_model, "encode"):
                embedding_model.encode(
                    ["warmup"],
                    normalize_embeddings=True,
                )
        except Exception as error:
            errors.append(error)

        try:
            reranker_model = self.get_reranker_model()
            if hasattr(reranker_model, "predict"):
                reranker_model.predict([("warmup", "warmup")])
        except Exception as error:
            errors.append(error)

        if errors:
            raise ModelPreloadError(
                "One or more RAG models failed to preload"
            ) from errors[0]

    def status(self) -> ModelRegistryStatus:
        with self._embedding_lock:
            embedding_state = self._embedding_state
        with self._reranker_lock:
            reranker_state = self._reranker_state
        return ModelRegistryStatus(
            embedding=embedding_state,
            reranker=reranker_state,
        )

    def _load_embedding_model(self) -> SentenceTransformer:
        config = rag_config["retriever"]
        local_path = settings.local_model_path("embedding")
        if local_path:
            return SentenceTransformer(
                str(local_path),
                local_files_only=True,
            )

        revision = config.get("embedding_revision")
        model_kwargs = {"revision": revision} if revision else {}
        return SentenceTransformer(
            config["embedding_model"],
            **model_kwargs,
        )

    def _load_reranker_model(self) -> CrossEncoder:
        config = rag_config["reranker"]
        local_path = settings.local_model_path("reranker")
        if local_path:
            model = CrossEncoder(
                str(local_path),
                local_files_only=True,
            )
        else:
            revision = config.get("model_revision")
            model_kwargs = {"revision": revision} if revision else {}
            model = CrossEncoder(config["model_name"], **model_kwargs)

        adapter_path = config.get("adapter_path")
        if adapter_path:
            model.model = PeftModel.from_pretrained(
                model.model,
                adapter_path,
            )

        return model


model_registry = ModelRegistry()
