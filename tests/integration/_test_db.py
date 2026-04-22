from sqlalchemy import create_engine, text, Column, String, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from pgvector.sqlalchemy import Vector
import uuid

DB_URL = "postgresql://rag_user:rag_password@localhost:5432/rag_vectordb"

Base = declarative_base()

class TestDocument(Base):
    __tablename__ = "test_rag_docs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    content = Column(Text)
    embedding = Column(Vector(3))


def test_pgvector_insert_and_read():
    engine = create_engine(DB_URL)

    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    Base.metadata.create_all(engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        session.query(TestDocument).delete()

        doc = TestDocument(
            content="Hello CSSA-AI! 这是我们存入数据库的第一条 RAG 知识。",
            embedding=[0.1, 0.5, 0.9]
        )
        session.add(doc)
        session.commit()

        result = session.query(TestDocument).first()

        assert result is not None
        assert result.content == "Hello CSSA-AI! 这是我们存入数据库的第一条 RAG 知识。"
        assert len(result.embedding) == 3
    finally:
        session.close()