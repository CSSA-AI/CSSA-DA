"""create chat_interactions table

Revision ID: 20260824_0005
Revises: 20260713_0004
Create Date: 2026-08-24

Six columns, deliberately (ROADMAP_rag.md Phase 4.5). Everything else the
table will eventually carry — feedback, user_id, session_id, token_usage,
refused — is a nullable ADD COLUMN later, which satisfies the hard rule in
ROADMAP_platform.md 11.1: after this migration runs, the previous version of
the code must still work. Adding a table always does.

Note on `retrieved`: it stores `article.id`, which is the stable
link-derived doc_id since CSS-7 (`wx_<slug>` for WeChat), so these rows join
back to knowledge_base.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260824_0005"
down_revision = "20260713_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_interactions",
        # The X-Request-ID already on the response header, so a row can be
        # joined to the request's log lines (ROADMAP_rag.md 4.1: logs carry
        # request_id + doc_id + score + rank, this table carries query +
        # answer).
        sa.Column("request_id", sa.Text(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        # [{doc_id, score, rank}], post-rerank order.
        sa.Column("retrieved", postgresql.JSONB(), nullable=True),
        # Config fingerprint — without it, six months from now you cannot
        # tell which rows predate a model swap and the whole batch loses its
        # comparative value.
        sa.Column("config", postgresql.JSONB(), nullable=True),
    )
    # Every analytical query over this table is "recent traffic first" or a
    # time window; nothing reads it by request_id except a targeted postmortem.
    op.create_index(
        "chat_interactions_created_at_idx",
        "chat_interactions",
        [sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "chat_interactions_created_at_idx",
        table_name="chat_interactions",
    )
    op.drop_table("chat_interactions")
