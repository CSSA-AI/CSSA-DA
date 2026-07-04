import argparse
import os

from app.services.rag.retriever.pg_retriever import PGVectorRetriever


def smoke_test_retrieval(
    query: str,
    database_url: str,
    *,
    top_k: int = 1,
) -> int:
    retriever = PGVectorRetriever(database_url=database_url)

    try:
        results = retriever.search(query, top_k=top_k)
    finally:
        retriever.close()

    print(f"Query: {query}")
    print(f"Results found: {len(results)}")

    if not results:
        print("No retrieval results found.")
        return 1

    top_result = results[0]
    article = top_result.article

    print(f"Top score: {top_result.score}")
    print(f"Top question: {article.questions[0] if article.questions else ''}")
    print(f"Top source: {article.source}")
    print(f"Top link: {article.link}")

    if not article.link:
        print("Top result is missing link.")
        return 1

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test PGVector retrieval against imported knowledge_base rows."
    )
    parser.add_argument(
        "--query",
        default="墨尔本 校招",
        help="Query text to search.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="Postgres connection URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=1,
        help="Number of retrieval results to request.",
    )
    args = parser.parse_args()

    if not args.database_url:
        raise ValueError("DATABASE_URL is required")

    return smoke_test_retrieval(
        query=args.query,
        database_url=args.database_url,
        top_k=args.top_k,
    )


if __name__ == "__main__":
    raise SystemExit(main())
