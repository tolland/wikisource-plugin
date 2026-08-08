"""fetchrequest: how many revisions to store

Adds ``fetchrequest.revisions``. A normal fetch stores the head and nothing
else, which is all the VFS and the editor need -- but it is not enough for the
cross-site anchor search: a page imported from an older revision of the other
side has no match at the head, and comparing heads can never find one.

Defaults to 1 with a server default, so rows written before this migration (and
by any client that does not know the field) mean "just the head", which is what
they meant already.

Revision ID: d3b8f7a21c94
Revises: a9e47c3d18f5
Create Date: 2026-08-09 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3b8f7a21c94"
down_revision: str | None = "a9e47c3d18f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Plain add_column, never batch_alter_table: batch mode rebuilds the table
    # on SQLite (create, copy, DROP TABLE, rename), and `fetchrequest`
    # references itself through parent_pk as well as site, so the drop fails
    # under PRAGMA foreign_keys=ON.
    op.add_column(
        "fetchrequest",
        sa.Column("revisions", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("fetchrequest", "revisions")
