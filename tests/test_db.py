from sqlalchemy import create_engine, text, Column, String, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from pgvector.sqlalchemy import Vector
import uuid

# 1. 数据库连接 URL (注意：这里的 host 是 postgres！)
DB_URL = "postgresql://rag_user:rag_password@postgres:5432/rag_vectordb"

print("🔄 正在尝试连接数据库...")
engine = create_engine(DB_URL)

# 2. 启用 pgvector 向量插件
with engine.connect() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    conn.commit()
    print("✅ pgvector 向量插件已就绪！")

# 3. 定义一张测试表 Schema
Base = declarative_base()

class TestDocument(Base):
    __tablename__ = 'test_rag_docs'
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    content = Column(Text)
    # 模拟一个 3 维向量 (真实业务中 OpenAI 的向量通常是 1536 维)
    embedding = Column(Vector(3))

# 4. 在数据库中真正建表 (如果表存在会跳过)
Base.metadata.create_all(engine)
print("✅ 测试表 'test_rag_docs' 创建成功！")

# 5. 插入一条测试数据
Session = sessionmaker(bind=engine)
session = Session()

# 每次运行前先清空旧数据，保持测试环境干净
session.query(TestDocument).delete()

# 创建一条新数据
doc = TestDocument(
    content="Hello CSSA-AI! 这是我们存入数据库的第一条 RAG 知识。",
    embedding=[0.1, 0.5, 0.9]
)
session.add(doc)
session.commit()
print("✅ 成功插入了一条包含向量的测试数据！")

# 6. 读取出来验证一下
result = session.query(TestDocument).first()
print("\n🎉 === 最终测试结果 ===")
print(f"找到文档 ID: {result.id}")
print(f"文档内容: {result.content}")
print(f"文档向量: {result.embedding}")
print("========================\n")

session.close()