-- 创建 vector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 创建正式表
CREATE TABLE knowledge_base (
    id SERIAL PRIMARY KEY,
    question_text TEXT,
    content TEXT NOT NULL,
    source TEXT,
    author TEXT,
    post_date DATE,
    language TEXT,
    created_at DATE,
    tags JSONB,
    link TEXT,
    embedding VECTOR(384)
);

-- 查看数据条数
SELECT COUNT(*) FROM knowledge_base;

-- 查看前几条数据
SELECT id, question_text, source, post_date
FROM knowledge_base
LIMIT 10;

-- 查看 embedding
SELECT embedding
FROM knowledge_base
LIMIT 1;

-- 相似度检索测试
SELECT
    id,
    question_text,
    post_date
FROM knowledge_base
ORDER BY embedding <-> (
    SELECT embedding
    FROM knowledge_base
    WHERE id = 1
)
LIMIT 5;