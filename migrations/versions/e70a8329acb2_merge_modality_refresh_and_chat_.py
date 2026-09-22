"""merge modality refresh and chat interactions

Revision ID: e70a8329acb2
Revises: 20260817_0005, 20260824_0005
Create Date: 2026-08-31 13:18:59.312634

Backward compatibility (CONTRIBUTING.md, "Database migrations"): after this
migration runs, the previous version of the code must still work. Say why it
does — or which of the two deploys this one is.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e70a8329acb2'
down_revision: Union[str, None] = ('20260817_0005', '20260824_0005')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
