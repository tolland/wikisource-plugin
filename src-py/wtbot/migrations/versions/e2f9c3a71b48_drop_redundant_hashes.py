"""drop redundant hash/size columns

Three columns removed, all of them a second name for a value the revision store
already holds under a first one:

- ``revision.remote_sha1`` / ``revision.remote_size``. For a single-slot
  revision MediaWiki's ``rev_sha1`` *is* the main slot's ``content_sha1`` and
  ``rev_len`` its ``content_size`` -- verified against a real wiki's storage
  layer. Upstream reached the same conclusion: T389026 is resolved as "drop
  rev_sha1 and compute it on the fly from content_sha1".
- ``page.sha1``. Nothing read it, and it held the *remote* hash in *hex* while
  ``content.content_sha1`` holds *ours* in *base-36* -- the same name for a
  different quantity in a different encoding, which is precisely the confusion
  this change exists to remove.

No data is lost: everything dropped here is still available through
``page -> revision -> slot -> content``, in a single normalised encoding.

Revision ID: e2f9c3a71b48
Revises: d4a7b1e6c5f2
Create Date: 2026-07-29 06:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2f9c3a71b48"
down_revision: str | None = "d5e30ab914c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Plain drop_column, NOT batch_alter_table. SQLite's batch mode rebuilds the
    # table -- create, copy, DROP TABLE, rename -- and under
    # ``PRAGMA foreign_keys=ON`` dropping `revision` fails as soon as any
    # `slot` row references it. Native ALTER TABLE DROP COLUMN (SQLite >= 3.35)
    # touches no other table, so the foreign keys never come into it.
    op.drop_column("revision", "remote_sha1")
    op.drop_column("revision", "remote_size")
    op.drop_column("page", "sha1")


def downgrade() -> None:
    op.add_column("page", sa.Column("sha1", sa.String(), nullable=True))
    op.add_column("revision", sa.Column("remote_size", sa.Integer(), nullable=True))
    op.add_column("revision", sa.Column("remote_sha1", sa.String(), nullable=True))
