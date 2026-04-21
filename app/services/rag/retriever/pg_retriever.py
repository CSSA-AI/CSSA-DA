import psycopg2
from psycopg2.extras import RealDictCursor
from sentence_transformers import SentenceTransformer
from typing import List

from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.retriever.base import BaseRetriever


class PGVectorRetriever(BaseRetriever):
    def __init__(self, db_config: dict, model_name: str):
        """
        db_config example:
        {
            "host": "localhost",
            "port": 5432,
            "dbname": "postgres",
            "user": "postgres",
            "password": "postgres"
        }
        """
        super().__init__(input_list=[], model_name=model_name)

        # DB connection
        self.conn = psycopg2.connect(**db_config)

        # Embedding model
        self.model = SentenceTransformer(model_name)

    def _encode_query(self, query: str):
        """Encode query into normalized embedding"""
        return self.model.encode(
            [query],
            normalize_embeddings=True
        )[0]

    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        """Main retrieval function"""
        try:
            vec = self._encode_query(query)

            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT
                        question_text,
                        content,
                        source,
                        author,
                        post_date,
                        language,
                        created_at,
                        tags,
                        link,
                        embedding <-> %s AS distance
                    FROM knowledge_base
                    ORDER BY embedding <-> %s
                    LIMIT %s;
                """, (vec.tolist(), vec.tolist(), top_k))

                rows = cursor.fetchall()

            results = []

            for i, row in enumerate(rows):
                article = Article(
                    text=row["content"],
                    questions=[row["question_text"]] if row["question_text"] else [],
                    source=row["source"],
                    author=row["author"],
                    post_date=row["post_date"],
                    language=row["language"],
                    created_at=row["created_at"],
                    tags=row["tags"] if isinstance(row["tags"], list) else [],
                    link=row["link"]
                )

                result = SearchResult(
                    article=article,
                    score=-float(row["distance"]),  # ✅ 转成“越大越好”
                    rank=i
                )

                results.append(result)

            return results

        except Exception as e:
            print(f"[PGVectorRetriever ERROR]: {e}")
            return []