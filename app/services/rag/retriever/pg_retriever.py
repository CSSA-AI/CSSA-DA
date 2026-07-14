import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from psycopg2.pool import PoolError, ThreadedConnectionPool
from sentence_transformers import SentenceTransformer
from typing import List, Optional

from app.core.config import settings, rag_config
from app.schemas.article import Article
from app.schemas.search_result import SearchResult
from app.services.rag.errors import RetrievalUnavailableError
from app.services.rag.retriever.base import BaseRetriever


class PGVectorRetriever(BaseRetriever):
    def __init__(
        self,
        database_url: Optional[str] = None,
        model_name: Optional[str] = None,
        model_revision: Optional[str] = None,
        table_name: Optional[str] = None,
        pool_min_size: Optional[int] = None,
        pool_max_size: Optional[int] = None,
    ):
        retriever_config = rag_config["retriever"]
        pgvector_config = rag_config["pgvector"]

        configured_model_name = retriever_config["embedding_model"]
        model_name = model_name or configured_model_name
        if (
            model_revision is None
            and model_name == configured_model_name
        ):
            model_revision = retriever_config.get("embedding_revision")
        database_url = database_url or settings.DATABASE_URL
        table_name = table_name or pgvector_config["table_name"]
        pool_min_size = pool_min_size or pgvector_config.get(
            "pool_min_size", 1
        )
        pool_max_size = pool_max_size or pgvector_config.get(
            "pool_max_size", 5
        )

        if not database_url:
            raise ValueError("DATABASE_URL is required for PGVectorRetriever")
        if pool_min_size <= 0:
            raise ValueError("pool_min_size must be greater than zero")
        if pool_max_size < pool_min_size:
            raise ValueError(
                "pool_max_size must be greater than or equal to pool_min_size"
            )

        super().__init__(
            model_name=model_name,
            model_revision=model_revision,
        )

        self.table_name = table_name
        self.pool = ThreadedConnectionPool(
            minconn=pool_min_size,
            maxconn=pool_max_size,
            dsn=database_url,
        )
        model_kwargs = (
            {"revision": self.model_revision}
            if self.model_revision
            else {}
        )
        self.model = SentenceTransformer(
            self.model_name,
            **model_kwargs,
        )

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
                embedding <-> %s::vector AS distance
            FROM {table}
            WHERE embedding_model = %s
              AND embedding_revision IS NOT DISTINCT FROM %s
            ORDER BY embedding <-> %s::vector
            LIMIT %s;
        """).format(
            table=sql.Identifier(self.table_name)
        )

        try:
            connection = self.pool.getconn()
        except (psycopg2.Error, PoolError) as error:
            raise RetrievalUnavailableError(
                "Unable to acquire a database connection"
            ) from error

        discard_connection = False
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    query_sql,
                    (
                        vec.tolist(),
                        self.model_name,
                        self.model_revision,
                        vec.tolist(),
                        top_k,
                    ),
                )
                rows = cursor.fetchall()
        except psycopg2.Error as error:
            raise RetrievalUnavailableError(
                "Knowledge-base query failed"
            ) from error
        finally:
            try:
                connection.rollback()
            except Exception:
                discard_connection = True
            self.pool.putconn(
                connection,
                close=discard_connection or bool(connection.closed),
            )

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
        """Close all database connections owned by the retriever."""
        self.pool.closeall()
