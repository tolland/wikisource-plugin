"""Add a per-site read throttle override.

Revision ID: e7f3b415fd0a
Revises: 8ac41e2d7f90
Create Date: 2026-08-15 00:16:30+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7f3b415fd0a"
down_revision: str | None = "8ac41e2d7f90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("site") as batch_op:
        batch_op.add_column(sa.Column("read_throttle", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("site") as batch_op:
        batch_op.drop_column("read_throttle")
