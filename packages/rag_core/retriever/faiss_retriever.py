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
        """
        Initialize the retriever with a list of Article objects and model name.

        Args:
            input_list (List[Article]): List of articles to index.
            model_name (str): HuggingFace model name for sentence encoding.
        """
        super().__init__()
        if not all(isinstance(x, Article) for x in input_list):
            raise TypeError("input_list must be a list of Article")

        self.articles = input_list
        self.model_name = model_name
        self.model = SentenceTransformer(self.model_name)

        self.id_mapping = {str(i): article for i, article in enumerate(self.articles)}
        self.title_embeddings = None
        self.index = None
        self._is_built = False

    def _encode_articles(self):
        """
        Encode all article titles into normalized sentence embeddings.
        The result is stored in self.title_embeddings (torch.Tensor).
        """
        titles = [a.title for a in self.articles]
        self.title_embeddings = self.model.encode(
            titles,
            convert_to_tensor=True,
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=True
        )
        return self.title_embeddings

    def _build_index(self):
        """
        Build a FAISS index (IndexFlatIP) using the encoded title embeddings.
        """
        if self.title_embeddings is None:
            raise RuntimeError("Must encode articles first")

        vectors = self.title_embeddings.detach().cpu().numpy().astype("float32")
        dim = vectors.shape[1]

        self.index = faiss.IndexFlatIP(dim)
        self.index.add(vectors)
        self._is_built = True

    def _encode_query(self, query: str) -> np.ndarray:
        """
        Encode a query string into a normalized float32 numpy vector.

        Args:
            query (str): The input query.

        Returns:
            np.ndarray: shape (1, embedding_dim)
        """
        vec = self.model.encode(
            [query],
            normalize_embeddings=True,
            convert_to_numpy=True
        ).astype("float32")
        return vec

    def search(self, query: str, top_k: int = 5) -> List[Tuple[int, float, Article]]:
        """
        Main retrieval method.

        Args:
            query (str): Query string.
            top_k (int): Number of top documents to return.

        Returns:
            List[Tuple[int, float, Article]]: List of (index, score, Article).
        """
        if not self._is_built:
            self._encode_articles()
            self._build_index()

        vec = self._encode_query(query)  # shape: (1, dim)
        scores, indices = self.index.search(vec, top_k)

        results = []
        for i, score in zip(indices[0], scores[0]):
            article = self.id_mapping[str(i)]
            results.append((int(i), float(score), article))
        return results

    def save_all(self, embed_path, index_path, idmap_path):
        """
        Save embeddings, FAISS index, and ID mapping to disk.

        Args:
            embed_path (str): Path to save .pt tensor.
            index_path (str): Path to save FAISS .index file.
            idmap_path (str): Path to save id-to-article mapping as JSON.
        """
        torch.save(self.title_embeddings.detach().cpu(), embed_path)
        faiss.write_index(self.index, index_path)
        with open(idmap_path, 'w') as f:
            json.dump({k: v.to_dict() for k, v in self.id_mapping.items()}, f, indent=4)

    def load_index(self, index_path):
        """
        Load an existing FAISS index from disk.

        Args:
            index_path (str): Path to .index file.
        """
        self.index = faiss.read_index(index_path)
        self._is_built = True
