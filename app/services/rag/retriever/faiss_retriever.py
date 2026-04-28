import json
import torch
import faiss
import numpy as np
from typing import List, Optional
from sentence_transformers import SentenceTransformer

from app.core.config import rag_config
from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.retriever.base import BaseRetriever


class FAISSRetriever(BaseRetriever):
    def __init__(
        self,
        input_list: List[Article],
        model_name: Optional[str] = None,
    ):
        retriever_config = rag_config["retriever"]

        model_name = model_name or retriever_config["embedding_model"]
        super().__init__(model_name=model_name)

        if not all(isinstance(x, Article) for x in input_list):
            raise TypeError("input_list must be a list of Article")

        self.articles = input_list
        self.model = SentenceTransformer(self.model_name)

        self.id_mapping = {i: article for i, article in enumerate(self.articles)}
        self.question_embeddings = None
        self.index = None
        self._is_built = False

    def _encode_articles(self):
        questions = []

        for article in self.articles:
            if not article.questions:
                raise ValueError(f"Article {article.id} has no questions")
            questions.append(article.questions[0])

        self.question_embeddings = self.model.encode(
            questions,
            convert_to_tensor=True,
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=True,
        )

        return self.question_embeddings

    def _build_index(self):
        if self.question_embeddings is None:
            raise RuntimeError("Must encode articles first")

        vectors = self.question_embeddings.detach().cpu().numpy().astype("float32")
        dim = vectors.shape[1]

        self.index = faiss.IndexFlatIP(dim)
        self.index.add(vectors)
        self._is_built = True

    def _encode_query(self, query: str) -> np.ndarray:
        return self.model.encode(
            [query],
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype("float32")

    def search(self, query: str, top_k: Optional[int] = None) -> List[SearchResult]:
        top_k = top_k or rag_config["retriever"]["top_k"]

        if not self._is_built:
            self._encode_articles()
            self._build_index()

        vec = self._encode_query(query)
        scores, indices = self.index.search(vec, top_k)

        results = []

        for rank, (i, score) in enumerate(zip(indices[0], scores[0]), start=1):
            if i == -1:
                continue

            article = self.id_mapping[i]

            results.append(
                SearchResult(
                    article=article,
                    score=float(score),
                    rank=rank,
                )
            )

        return results

    def save_all(
        self,
        embed_path: Optional[str] = None,
        index_path: Optional[str] = None,
        idmap_path: Optional[str] = None,
    ):
        faiss_config = rag_config["faiss"]

        embed_path = embed_path or faiss_config["embedding_path"]
        index_path = index_path or faiss_config["index_path"]
        idmap_path = idmap_path or faiss_config["idmap_path"]

        if self.question_embeddings is None or self.index is None:
            raise RuntimeError("Index must be built before saving")

        torch.save(self.question_embeddings.detach().cpu(), embed_path)
        faiss.write_index(self.index, index_path)

        with open(idmap_path, "w", encoding="utf-8") as f:
            json.dump(
                {str(k): v.model_dump(mode="json") for k, v in self.id_mapping.items()},
                f,
                indent=4,
                ensure_ascii=False,
            )

    def load_index(self, index_path: Optional[str] = None):
        index_path = index_path or rag_config["faiss"]["index_path"]

        self.index = faiss.read_index(index_path)
        self._is_built = True