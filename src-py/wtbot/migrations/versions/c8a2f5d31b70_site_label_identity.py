"""site: label as the operator-facing identity

``label`` existed as a free-text nicety. It becomes the name a person and the
CLI use for a wiki, so it has to be unique -- two sites called 'local' make
``--label local`` meaningless.

Existing rows are backfilled from ``family-code``, which is what they were
addressed by before and is unique by the table's own constraint, so the
backfill cannot collide. Rows that already carry a label keep it.

The column stays nullable. Fixtures construct Site objects directly and the
uniqueness that matters is between *named* sites; SQLite permits many NULLs in
a unique index, which is the behaviour wanted here. The creation surfaces (POST
/sites, ``wtbot site add``) require a label -- that is where the rule belongs,
because it is about how a wiki is addressed, not about what a row may hold.

Revision ID: c8a2f5d31b70
Revises: b7d1e4f95c30
Create Date: 2026-08-06 15:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8a2f5d31b70"
down_revision: str | None = "b7d1e4f95c30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE site SET label = family || '-' || code "
            "WHERE label IS NULL OR label = ''"
        )
    )
    # A plain index, never batch_alter_table: on SQLite batch mode rebuilds the
    # table (create, copy, DROP TABLE, rename), and `site` is referenced by
    # page, namespace, fetchrequest and sitecredential, so the drop fails under
    # PRAGMA foreign_keys=ON.
    op.create_index("uq_site_label", "site", ["label"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_site_label", table_name="site")
