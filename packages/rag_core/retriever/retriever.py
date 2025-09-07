import json
import torch
import os
import faiss
from transformers import BertTokenizer, BertModel
from sentence_transformers import SentenceTransformer
from packages.rag_core.utils.article import Article
import numpy as np

class Retriever:

    def __init__(self, input_list: list, model_name: str):

        for item in input_list:
            if not isinstance(item, Article):
                raise TypeError("input_list must be a list of Article")

        self.articles = input_list
        self.model_name  = model_name
        self.id_mapping = {}
        self.titles = None
        self.model = None
        self.title_embeddings = None
        self.index = None

    def vectorize_sentence_transformer(self, output_path: str = None):
        """
        Encode all article titles using a sentence-transformer model.
        Optionally save the embeddings to disk.
        """
        self.titles = [article.title for article in self.articles]

        # Load sentence-transformer model
        self.model = SentenceTransformer(self.model_name)
            
        # Encode all questions
        self.title_embeddings = self.model.encode(
            self.titles,
            batch_size=32,
            convert_to_tensor=True,
            show_progress_bar=True
        )
        
        if output_path:
            # Save embeddings
            torch.save(self.title_embeddings, output_path)
    
        print(f"Saved {len(self.titles)} embeddings to {output_path}, shape={self.title_embeddings.shape}")
        return self.title_embeddings
    
    def get_id_mapping(self, output_path: str = None):
        """
        Create a mapping from FAISS index ID to each Article object.
        Optionally save as JSON (converted to dict).
        """
        for idx, article in enumerate(self.articles):
            self.id_mapping[str(idx)] = article

        # save id:dict pair as json if necessary
        if output_path:
            id_mapping_json = {}
            for idx, article in enumerate(self.articles):
                id_mapping_json[str(idx)] = article.to_dict()

            with open(output_path, 'w') as f:
                json.dump(id_mapping_json, f, indent=4)

        return self.id_mapping
    
    
    def build_faiss_index(self, output_path: str = None):
        """
        Build a FAISS index from saved question embeddings and save it to disk.
        """
        if self.title_embeddings is None or self.title_embeddings.numel() == 0:
            raise RuntimeError("embeddings is not encoded yet. Run vectorize_title_st() first.")
        vectors = self.title_embeddings.numpy().astype("float32")  # Convert to float32 (FAISS requires this)
        # Get the embedding dimension
        dim = vectors.shape[1]

        # Create FAISS index (L2 distance metric)
        self.index = faiss.IndexFlatL2(dim)

        # Add all vectors to the index
        self.index.add(vectors)
        print(f"Indexed {vectors.shape[0]} vectors with dimension {dim}")

        if output_path:
            # Save the index to disk
            faiss.write_index(self.index, output_path)
            print(f"FAISS index saved to {output_path}")

        return self.index

    def _encode_query(self, query: str) -> np.ndarray:
        """
        Encode the query into a vector representation.
        - Use the same model as used to build the index
        - Normalize embeddings so that cosine similarity works properly
        """
        vec = self.model.encode([query], normalize_embeddings=True, convert_to_numpy=True).astype("float32")
        return vec
    
    def search(self, query: str, top_k: int = 5):
        """
        Search the FAISS index using the input query.
        Returns: List of (index, score, Article)
        """
        if self.index is None:
            raise RuntimeError("FAISS index is not built yet. Run build_faiss_index() first.")

        vec = self._encode_query(query)  # [1, dim]
        distances, indices = self.index.search(vec, top_k)

        results = []
        for i, score in zip(indices[0], distances[0]):
            article = self.id_mapping.get(str(i))
            results.append((i, float(score), article))
        return results

    def save_all(self, embed_path, index_path, idmap_path):
        """
        Save embeddings, index, id_mapping
        """
        torch.save(self.title_embeddings, embed_path)
        faiss.write_index(self.index, index_path)
        with open(idmap_path, 'w') as f:
            json.dump({k: v.to_dict() for k, v in self.id_mapping.items()}, f, indent=4)

    def load_index(self, index_path):
        """
        load index
        """
        self.index = faiss.read_index(index_path)
