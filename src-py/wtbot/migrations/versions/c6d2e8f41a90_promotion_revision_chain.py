"""preserve source revision boundaries in promotion chains

A promotion used to freeze only a page's head revision. Multiple source edits
were consequently written as one target edit. A self-reference makes each
source revision an explicit ordered step: the first uses the staged target
base and each later step uses the revid produced by its predecessor.

Revision ID: c6d2e8f41a90
Revises: b3f7ac21d908
Create Date: 2026-08-12 16:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6d2e8f41a90"
down_revision: str | None = "b3f7ac21d908"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("promotion") as batch_op:
        batch_op.add_column(
            sa.Column("predecessor_promotion_pk", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_promotion_predecessor_promotion_pk_promotion",
            "promotion",
            ["predecessor_promotion_pk"],
            ["pk"],
        )
        batch_op.create_index(
            "ix_promotion_predecessor_promotion_pk",
            ["predecessor_promotion_pk"],
        )


def downgrade() -> None:
    with op.batch_alter_table("promotion") as batch_op:
        batch_op.drop_index("ix_promotion_predecessor_promotion_pk")
        batch_op.drop_constraint(
            "fk_promotion_predecessor_promotion_pk_promotion", type_="foreignkey"
        )
        batch_op.drop_column("predecessor_promotion_pk")
