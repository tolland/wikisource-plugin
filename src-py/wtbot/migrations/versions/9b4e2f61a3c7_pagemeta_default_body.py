"""pagemeta default_body

Revision ID: 9b4e2f61a3c7
Revises: 6c6ead28332d
Create Date: 2026-07-19 00:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "9b4e2f61a3c7"
down_revision: str | None = "6c6ead28332d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pagemeta",
        sa.Column("default_body", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pagemeta", "default_body")
