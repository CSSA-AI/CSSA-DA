import pytest
import psycopg2

from app.services.rag.retriever.pg_retriever import PGVectorRetriever


# ✅ 统一的 db_config（测试用）
TEST_DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres",
    "password": "postgres"
}


# ✅ 1️⃣ 测试 db_config 是否能成功连接
def test_db_connection():
    conn = psycopg2.connect(**TEST_DB_CONFIG)
    assert conn is not None
    conn.close()


# ✅ 2️⃣ 测试 Retriever 初始化（db_config 是否正确传入）
def test_retriever_init():
    retriever = PGVectorRetriever(
        db_config=TEST_DB_CONFIG,
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )

    assert retriever.conn is not None
    assert retriever.model is not None


# ✅ 3️⃣ fixture（复用 retriever）
@pytest.fixture(scope="module")
def retriever():
    return PGVectorRetriever(
        db_config=TEST_DB_CONFIG,
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )


# ✅ 4️⃣ 测试 search 是否能正常跑
def test_search_runs(retriever):
    results = retriever.search("What is RAG?", top_k=3)

    assert isinstance(results, list)


# ✅ 5️⃣ 测试返回结构
def test_search_result_structure(retriever):
    results = retriever.search("What is RAG?", top_k=1)

    if len(results) == 0:
        pytest.skip("Database is empty")

    r = results[0]

    assert hasattr(r, "article")
    assert hasattr(r, "score")
    assert hasattr(r, "rank")


# ✅ 6️⃣ 测试 Article 字段
def test_article_fields(retriever):
    results = retriever.search("What is RAG?", top_k=1)

    if len(results) == 0:
        pytest.skip("Database is empty")

    article = results[0].article

    assert isinstance(article.text, str)
    assert isinstance(article.questions, list)
    assert isinstance(article.tags, list)


# ✅ 7️⃣ 测试 score 是 float（并且方向正确）
def test_score_type_and_order(retriever):
    results = retriever.search("What is RAG?", top_k=3)

    if len(results) < 2:
        pytest.skip("Not enough data")

    scores = [r.score for r in results]

    # score 应该是 float
    assert all(isinstance(s, float) for s in scores)

    # 应该是从大到小（因为我们做了 -distance）
    assert scores == sorted(scores, reverse=True)


# ✅ 8️⃣ 测试 top_k 生效
def test_top_k_limit(retriever):
    k = 2
    results = retriever.search("What is RAG?", top_k=k)

    assert len(results) <= k