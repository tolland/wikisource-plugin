"""Remove the shared refresh cursor; callers must provide their own since."""

import sqlalchemy as sa
from alembic import op

revision = "b72e8c913a04"
down_revision = "a21d6430c902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Native DROP COLUMN preserves the site table and its foreign-key dependents.
    op.drop_column("site", "changes_seen_through")


def downgrade() -> None:
    op.add_column(
        "site", sa.Column("changes_seen_through", sa.DateTime(), nullable=True)
    )
