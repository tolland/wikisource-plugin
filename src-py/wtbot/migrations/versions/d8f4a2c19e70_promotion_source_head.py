"""pin the source head observed by a granular promotion

Revision ID: d8f4a2c19e70
Revises: c6d2e8f41a90
Create Date: 2026-08-13 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8f4a2c19e70"
down_revision: str | None = "c6d2e8f41a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "promotion", sa.Column("source_head_revid", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("promotion", "source_head_revid")
