"""add embedding provenance to knowledge_base

Revision ID: 20260705_0003
Revises: 20260630_0002
Create Date: 2026-07-05
"""

import sqlalchemy as sa
from alembic import op


revision = "20260705_0003"
down_revision = "20260630_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_base",
        sa.Column("embedding_model", sa.Text(), nullable=True),
    )
    op.add_column(
        "knowledge_base",
        sa.Column("embedding_revision", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_base", "embedding_revision")
    op.drop_column("knowledge_base", "embedding_model")
