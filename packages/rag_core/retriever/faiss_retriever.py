'''
This is a Retriever that: 
- using FAISS techinique, 
- use only the original question (no question generated)
- use sentence-transformer
'''
import json
import torch
import faiss
import numpy as np
from typing import List, Tuple, Optional
from sentence_transformers import SentenceTransformer

from packages.rag_core.utils.article import Article
from packages.rag_core.retriever.base import BaseRetriever


class FAISSRetriever(BaseRetriever):
    def __init__(self, input_list: List[Article], model_name: str):
        super().__init__(input_list, model_name)

        if not all(isinstance(x, Article) for x in input_list):
            raise TypeError("input_list must be a list of Article")

        if not model_name:
            raise ValueError("FAISSRetriever requires a model_name.")

        self.model = SentenceTransformer(self.model_name)
        self.id_mapping = {i: article for i, article in enumerate(self.articles)}
        self.question_embeddings = None
        self.index = None
        self._is_built = False

    def _encode_articles(self):
        """Encode each article’s first question into normalized embeddings."""
        questions = []
        for a in self.articles:
            if not a.questions:
                raise ValueError(f"Article {a.id} has no questions")
            questions.append(a.questions[0])

        self.question_embeddings = self.model.encode(
            questions,
            convert_to_tensor=True,
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=True
        )
        return self.question_embeddings

    def _build_index(self):
        """Build a FAISS index (IndexFlatIP) using the encoded question embeddings."""
        if self.question_embeddings is None:
            raise RuntimeError("Must encode articles first")

        vectors = self.question_embeddings.detach().cpu().numpy().astype("float32")
        dim = vectors.shape[1]

        self.index = faiss.IndexFlatIP(dim)
        self.index.add(vectors)
        self._is_built = True

    def _encode_query(self, query: str) -> np.ndarray:
        """Encode a query string into a normalized float32 numpy vector."""
        vec = self.model.encode(
            [query],
            normalize_embeddings=True,
            convert_to_numpy=True
        ).astype("float32")
        return vec

    def search(self, query: str, top_k: int = 5) -> List[Tuple[int, float, Article]]:
        """Retrieve top-k articles given a query string."""
        if not self._is_built:
            self._encode_articles()
            self._build_index()

        vec = self._encode_query(query)  # shape: (1, dim)
        scores, indices = self.index.search(vec, top_k)

        results = []
        for i, score in zip(indices[0], scores[0]):
            article = self.id_mapping[i]
            results.append((int(i), float(score), article))
        return results

    def save_all(self, embed_path, index_path, idmap_path):
        """Save embeddings, FAISS index, and ID mapping to disk."""
        torch.save(self.question_embeddings.detach().cpu(), embed_path)
        faiss.write_index(self.index, index_path)
        with open(idmap_path, 'w') as f:
            json.dump({str(k): v.to_dict() for k, v in self.id_mapping.items()}, f, indent=4)

    def load_index(self, index_path):
        """Load an existing FAISS index from disk."""
        self.index = faiss.read_index(index_path)
        self._is_built = True
