"""create pipeline_runs table

Revision ID: 20260713_0004
Revises: 20260705_0003
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from alembic import op


revision = "20260713_0004"
down_revision = "20260705_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("pipeline_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_path", sa.Text(), nullable=True),
        sa.Column("output_path", sa.Text(), nullable=True),
        sa.Column("report_path", sa.Text(), nullable=True),
        sa.Column("record_count", sa.Integer(), nullable=True),
        sa.Column("affected_count", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "pipeline_runs_pipeline_started_idx",
        "pipeline_runs",
        ["pipeline_name", "started_at"],
    )
    op.create_index(
        "pipeline_runs_status_idx",
        "pipeline_runs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("pipeline_runs_status_idx", table_name="pipeline_runs")
    op.drop_index(
        "pipeline_runs_pipeline_started_idx",
        table_name="pipeline_runs",
    )
    op.drop_table("pipeline_runs")
