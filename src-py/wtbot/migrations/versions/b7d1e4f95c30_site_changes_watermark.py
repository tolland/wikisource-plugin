"""site: recentchanges watermark

Adds ``site.changes_seen_through``, the position in a wiki's change stream that
an incremental refresh resumes from (see wtbot.incremental). Per site, because
two wikis holding the same work have unrelated change streams.

Nullable with no default: NULL means "never refreshed incrementally", which
must stay distinguishable from "refreshed, and nothing had changed". Defaulting
it to the migration time would assert we had seen every change up to then,
silently skipping everything that moved before this deploy.

Revision ID: b7d1e4f95c30
Revises: a3f61d2b7c85
Create Date: 2026-08-05 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d1e4f95c30"
down_revision: str | None = "a3f61d2b7c85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Plain add_column, never batch_alter_table: on SQLite batch mode rebuilds
    # the table (create, copy, DROP TABLE, rename), and `site` is referenced by
    # page, namespace, fetchrequest and sitecredential, so the drop fails under
    # PRAGMA foreign_keys=ON.
    op.add_column(
        "site", sa.Column("changes_seen_through", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("site", "changes_seen_through")
