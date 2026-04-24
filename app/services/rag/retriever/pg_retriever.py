import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from sentence_transformers import SentenceTransformer
from typing import List, Optional

from app.core.config import settings, rag_config
from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.retriever.base import BaseRetriever


class PGVectorRetriever(BaseRetriever):
    def __init__(
        self,
        database_url: Optional[str] = None,
        model_name: Optional[str] = None,
        table_name: Optional[str] = None,
    ):
        retriever_config = rag_config["retriever"]
        pgvector_config = rag_config["pgvector"]

        model_name = model_name or retriever_config["embedding_model"]
        database_url = database_url or settings.DATABASE_URL
        table_name = table_name or pgvector_config["table_name"]

        if not database_url:
            raise ValueError("DATABASE_URL is required for PGVectorRetriever")

        super().__init__(model_name=model_name)

        self.table_name = table_name
        self.conn = psycopg2.connect(database_url)
        self.model = SentenceTransformer(self.model_name)

    def _encode_query(self, query: str):
        """Encode query into normalized embedding."""
        return self.model.encode(
            [query],
            normalize_embeddings=True,
        )[0]

    def search(self, query: str, top_k: Optional[int] = None) -> List[SearchResult]:
        """Retrieve top-k most similar chunks from pgvector."""
        top_k = top_k or rag_config["retriever"]["top_k"]
        vec = self._encode_query(query)

        query_sql = sql.SQL("""
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
            FROM {table}
            ORDER BY embedding <-> %s
            LIMIT %s;
        """).format(
            table=sql.Identifier(self.table_name)
        )

        with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query_sql, (vec.tolist(), vec.tolist(), top_k))
            rows = cursor.fetchall()

        results = []

        for rank, row in enumerate(rows, start=1):
            article = Article(
                text=row["content"],
                questions=[row["question_text"]] if row["question_text"] else [],
                source=row["source"],
                author=row["author"],
                post_date=row["post_date"],
                language=row["language"],
                created_at=row["created_at"],
                tags=row["tags"] if isinstance(row["tags"], list) else [],
                link=row["link"],
            )

            results.append(
                SearchResult(
                    article=article,
                    score=-float(row["distance"]),
                    rank=rank,
                )
            )

        return results

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()