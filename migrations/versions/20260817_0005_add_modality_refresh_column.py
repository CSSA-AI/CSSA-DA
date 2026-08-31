"""add modality and refresh columns to knowledge_base

Adds nullable `modality` and `refresh` text columns to `knowledge_base`.
Backfills `modality` to 'doc' for existing rows, and `refresh` to
'append' for WeChat sources and 'replace' for handbook sources.

Revision ID: 20260817_0005
Revises: 20260713_0004
Create Date: 2026-08-17

"""

import sqlalchemy as sa
from alembic import op


revision = "20260817_0005"
down_revision = "20260713_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_base",
        sa.Column("modality", sa.Text(), nullable=True),
    )
    op.add_column(
        "knowledge_base",
        sa.Column("refresh", sa.Text(), nullable=True),
    )
    op.execute("UPDATE knowledge_base SET modality = 'doc' WHERE modality IS NULL")
    op.execute(
        "UPDATE knowledge_base SET refresh = 'append' WHERE source LIKE 'WeChat%'"
    )
    op.execute(
        "UPDATE knowledge_base SET refresh = 'replace' WHERE refresh IS NULL")


def downgrade() -> None:
    op.drop_column("knowledge_base", "refresh")
    op.drop_column("knowledge_base", "modality")
