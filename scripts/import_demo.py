import json
import psycopg2
from sentence_transformers import SentenceTransformer
from app.core.config import rag_config

# 1. 加载 embedding 模型
model = SentenceTransformer(rag_config["retriever"]["embedding_model"])

# 2. 连接数据库
conn = psycopg2.connect(
    host="postgres",
    port=5432,
    dbname="rag_vectordb",
    user="rag_user",
    password="rag_password"
)

cur = conn.cursor()

# 3. 打开 JSON 文件
with open("data/demo_data.json", "r", encoding="utf-8") as f:
    data = json.load(f)

# 4. 一条一条读取并插入
for item in data:
    questions = item.get("questions", [])
    question_text = questions[0] if questions else None

    content = item.get("text")
    source = item.get("source")
    author = item.get("author")
    post_date = item.get("post_date")
    language = item.get("language")
    created_at = item.get("created_at")
    tags = json.dumps(item.get("tags", []), ensure_ascii=False)
    link = item.get("link")

    # 用 question + content 一起生成 embedding
    text_for_embedding = ""
    if question_text:
        text_for_embedding += question_text + "\n"
    if content:
        text_for_embedding += content

    embedding = model.encode(text_for_embedding, normalize_embeddings=True).tolist()

    cur.execute("""
        INSERT INTO knowledge_base (
            question_text,
            content,
            source,
            author,
            post_date,
            language,
            created_at,
            tags,
            link,
            embedding
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        question_text,
        content,
        source,
        author,
        post_date,
        language,
        created_at,
        tags,
        link,
        embedding
    ))

# 5. 提交并关闭
conn.commit()
cur.close()
conn.close()

print("真实 embedding 导入成功！")
