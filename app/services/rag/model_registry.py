from threading import Lock

from peft import PeftModel
from sentence_transformers import CrossEncoder, SentenceTransformer

from app.core.config import rag_config, settings


class ModelRegistry:
    """Load and share the configured embedding and reranker models."""

    def __init__(self) -> None:
        self._embedding_model: SentenceTransformer | None = None
        self._reranker_model: CrossEncoder | None = None
        self._embedding_lock = Lock()
        self._reranker_lock = Lock()

    def get_embedding_model(self) -> SentenceTransformer:
        if self._embedding_model is None:
            with self._embedding_lock:
                if self._embedding_model is None:
                    self._embedding_model = self._load_embedding_model()
        return self._embedding_model

    def get_reranker_model(self) -> CrossEncoder:
        if self._reranker_model is None:
            with self._reranker_lock:
                if self._reranker_model is None:
                    self._reranker_model = self._load_reranker_model()
        return self._reranker_model

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
