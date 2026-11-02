"""Track arbitrary page trees through their root page pairing."""

import sqlalchemy as sa
from alembic import op

revision = "c92a713e4b06"
down_revision = "a71b9d42e608"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pagetreelink",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["pk"], ["pagelink.pk"]),
        sa.PrimaryKeyConstraint("pk"),
    )


def downgrade() -> None:
    op.drop_table("pagetreelink")
