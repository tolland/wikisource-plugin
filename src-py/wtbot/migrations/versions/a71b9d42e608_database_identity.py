"""Give each cache database a persistent identity.

Revision ID: a71b9d42e608
Revises: f3c8a2e7d914
"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "a71b9d42e608"
down_revision = "f3c8a2e7d914"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "databaseidentity",
        sa.Column("pk", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("uuid", sa.String(), nullable=False),
        sa.CheckConstraint("pk = 1", name="singleton"),
    )
    op.bulk_insert(table, [{"pk": 1, "uuid": str(uuid4())}])


def downgrade() -> None:
    op.drop_table("databaseidentity")
