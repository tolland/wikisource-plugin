"""drop site.host

``host`` was written by the registration surfaces and displayed by the viewer,
and read by nothing: every behavioral path -- pywikibot construction, the VFS,
preview, OCR, commits -- goes through ``api_url`` or the (family, code) pair.
A column that only ever echoes its input back is a second place for the
endpoint to be wrong.

Revision ID: a9e47c3d18f5
Revises: c8a2f5d31b70
Create Date: 2026-08-06 00:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9e47c3d18f5"
down_revision: str | None = "c8a2f5d31b70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Plain drop_column, NOT batch_alter_table: batch mode rebuilds the table,
    # and under ``PRAGMA foreign_keys=ON`` dropping `site` fails as soon as any
    # row references it. Native ALTER TABLE DROP COLUMN (SQLite >= 3.35)
    # touches no other table. Same reasoning as e2f9c3a71b48.
    op.drop_column("site", "host")


def downgrade() -> None:
    op.add_column("site", sa.Column("host", sa.String(), nullable=True))
