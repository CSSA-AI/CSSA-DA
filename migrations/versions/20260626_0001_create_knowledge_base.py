"""create knowledge_base table

Revision ID: 20260626_0001
Revises:
Create Date: 2026-06-26
"""

from alembic import op


revision = "20260626_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id SERIAL PRIMARY KEY,
            question_text TEXT,
            content TEXT NOT NULL,
            source TEXT,
            author TEXT,
            post_date DATE,
            language TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            tags JSONB,
            link TEXT,
            embedding VECTOR(384)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_base")
