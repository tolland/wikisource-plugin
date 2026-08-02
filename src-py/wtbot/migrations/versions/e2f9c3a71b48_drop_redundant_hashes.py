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
down_revision: str | None = "d4a7b1e6c5f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("revision", schema=None) as batch_op:
        batch_op.drop_column("remote_sha1")
        batch_op.drop_column("remote_size")

    with op.batch_alter_table("page", schema=None) as batch_op:
        batch_op.drop_column("sha1")


def downgrade() -> None:
    with op.batch_alter_table("page", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sha1", sa.String(), nullable=True))

    with op.batch_alter_table("revision", schema=None) as batch_op:
        batch_op.add_column(sa.Column("remote_size", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("remote_sha1", sa.String(), nullable=True))
