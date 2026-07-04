"""add knowledge_base dedupe index

Revision ID: 20260630_0002
Revises: 20260626_0001
Create Date: 2026-06-30
"""

from alembic import op


revision = "20260630_0002"
down_revision = "20260626_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM knowledge_base a
        USING knowledge_base b
        WHERE a.id > b.id
          AND a.link IS NOT DISTINCT FROM b.link
          AND a.question_text IS NOT DISTINCT FROM b.question_text
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS knowledge_base_link_question_text_idx
        ON knowledge_base (link, question_text)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS knowledge_base_link_question_text_idx")
