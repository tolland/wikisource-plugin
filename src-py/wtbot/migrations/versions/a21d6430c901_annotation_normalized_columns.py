"""Stage normalized geometry for an offline annotation backfill."""

import sqlalchemy as sa
from alembic import op

revision = "a21d6430c901"
down_revision = "f19c2d4a7b31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite DDL may survive a later migration failure while its revision
    # stamp rolls back. Allow the staging step to be retried in that case.
    existing = {
        c["name"] for c in sa.inspect(op.get_bind()).get_columns("scanannotation")
    }
    for name in ("x", "y", "width", "height"):
        if f"normalized_{name}" in existing:
            continue
        op.add_column(
            "scanannotation", sa.Column(f"normalized_{name}", sa.Float(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("scanannotation") as batch:
        for name in ("x", "y", "width", "height"):
            batch.drop_column(f"normalized_{name}")
