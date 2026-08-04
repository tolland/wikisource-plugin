"""remotelink: unique on the unordered pair

``uq_link`` was unique over (local, remote) in that order, so the identical
correspondence asserted the other way round -- (remote, local) -- passed
straight through it. Neither side is privileged: ``local``/``remote`` record
the direction an assertion was made from, not a hierarchy, and "A corresponds
to B" is the same fact as "B corresponds to A". Two rows for one fact would
give a page pair two ladders and two anchors that could disagree, which is an
error every layer above this table would inherit.

Replaced by a unique index over ``min(local, remote), max(local, remote)``.
SQLite indexes expressions, so the pair is canonicalised for the index without
the columns having to lie about which side is which. The old constraint is not
merely redundant afterwards, it is subsumed: any two rows equal on
(local, remote) are also equal on (min, max).

Separate migration rather than an edit to f9c04b7e51a2, which may already have
been applied to a development database -- rewriting an applied migration leaves
the version table claiming an index that is not there.

Revision ID: a3f61d2b7c85
Revises: f9c04b7e51a2
Create Date: 2026-08-04 14:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3f61d2b7c85"
down_revision: str | None = "f9c04b7e51a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A named table-level UNIQUE is enforced by an internal `sqlite_autoindex_...`,
# not by an index called `uq_link`, so it cannot be dropped with DROP INDEX --
# removing it means rebuilding the table. That is safe *here* and nowhere else
# in this schema: `remotelink` has foreign keys pointing outwards, at
# `revision`, and no table points back at it, so the DROP that trips up a
# rebuild of `page` or `revision` has nothing to trip over. Rows are copied, so
# a development database that already holds links keeps them.


def _create_indexes() -> None:
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


def upgrade() -> None:
    # Any pre-existing reversed duplicate would make the new index
    # unbuildable. Keep the earliest assertion of each unordered pair -- the
    # ladder's first rung is the one with a history behind it.
    op.execute(
        sa.text(
            "DELETE FROM remotelink WHERE pk NOT IN ("
            " SELECT min(pk) FROM remotelink"
            " GROUP BY min(local_revision_pk, remote_revision_pk),"
            "          max(local_revision_pk, remote_revision_pk))"
        )
    )

    op.create_table(
        "remotelink_new",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("local_revision_pk", sa.Integer(), nullable=False),
        sa.Column("remote_revision_pk", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["local_revision_pk"], ["revision.pk"]),
        sa.ForeignKeyConstraint(["remote_revision_pk"], ["revision.pk"]),
        sa.PrimaryKeyConstraint("pk"),
    )
    op.execute(
        sa.text(
            "INSERT INTO remotelink_new (pk, local_revision_pk,"
            " remote_revision_pk, origin)"
            " SELECT pk, local_revision_pk, remote_revision_pk, origin"
            " FROM remotelink"
        )
    )
    op.drop_index(op.f("ix_remotelink_remote_revision_pk"), table_name="remotelink")
    op.drop_index(op.f("ix_remotelink_local_revision_pk"), table_name="remotelink")
    op.drop_table("remotelink")
    op.rename_table("remotelink_new", "remotelink")

    _create_indexes()
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_remotelink_pair ON remotelink"
            " (min(local_revision_pk, remote_revision_pk),"
            "  max(local_revision_pk, remote_revision_pk))"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS uq_remotelink_pair"))

    op.create_table(
        "remotelink_old",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("local_revision_pk", sa.Integer(), nullable=False),
        sa.Column("remote_revision_pk", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["local_revision_pk"], ["revision.pk"]),
        sa.ForeignKeyConstraint(["remote_revision_pk"], ["revision.pk"]),
        sa.PrimaryKeyConstraint("pk"),
        sa.UniqueConstraint("local_revision_pk", "remote_revision_pk", name="uq_link"),
    )
    op.execute(
        sa.text(
            "INSERT INTO remotelink_old (pk, local_revision_pk,"
            " remote_revision_pk, origin)"
            " SELECT pk, local_revision_pk, remote_revision_pk, origin"
            " FROM remotelink"
        )
    )
    op.drop_index(op.f("ix_remotelink_remote_revision_pk"), table_name="remotelink")
    op.drop_index(op.f("ix_remotelink_local_revision_pk"), table_name="remotelink")
    op.drop_table("remotelink")
    op.rename_table("remotelink_old", "remotelink")

    _create_indexes()
