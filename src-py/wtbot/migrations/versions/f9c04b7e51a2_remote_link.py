"""remote link: asserted cross-site revision correspondence

Adds ``remotelink``, one row per assertion that a local revision and a remote
one hold the same content (docs/done/upstream-sync-built.md). Purely additive:
no existing table is touched, so nothing here can rebuild a table that something
references.

The table is append-only by convention rather than by trigger -- the store
module is the only writer and offers no update or delete -- so a superseded
correspondence stays visible as an earlier rung of the ladder.

Revision ID: f9c04b7e51a2
Revises: e2f9c3a71b48
Create Date: 2026-08-04 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f9c04b7e51a2"
down_revision: str | None = "e2f9c3a71b48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "remotelink",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("local_revision_pk", sa.Integer(), nullable=False),
        sa.Column("remote_revision_pk", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["local_revision_pk"], ["revision.pk"]),
        sa.ForeignKeyConstraint(["remote_revision_pk"], ["revision.pk"]),
        sa.PrimaryKeyConstraint("pk"),
        sa.UniqueConstraint("local_revision_pk", "remote_revision_pk", name="uq_link"),
    )
    op.create_index(
        op.f("ix_remotelink_local_revision_pk"),
        "remotelink",
        ["local_revision_pk"],
        unique=False,
    )
    op.create_index(
        op.f("ix_remotelink_remote_revision_pk"),
        "remotelink",
        ["remote_revision_pk"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_remotelink_remote_revision_pk"), table_name="remotelink")
    op.drop_index(op.f("ix_remotelink_local_revision_pk"), table_name="remotelink")
    op.drop_table("remotelink")
