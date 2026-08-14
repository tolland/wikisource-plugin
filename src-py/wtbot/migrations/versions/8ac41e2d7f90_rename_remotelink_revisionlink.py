"""rename remotelink to revisionlink

Revision ID: 8ac41e2d7f90
Revises: 47b1d0e8a625
Create Date: 2026-08-14 23:15:00.000000+00:00

The Python model was renamed because the link relates revisions, not remote
pages. This revision makes the persisted schema agree. Indexes are recreated
under the new table-derived names as SQLite cannot rename an index.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8ac41e2d7f90"
down_revision: str | None = "47b1d0e8a625"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_indexes(prefix: str) -> None:
    op.execute(sa.text(f"DROP INDEX uq_{prefix}_pair"))
    op.drop_index(f"ix_{prefix}_page_link_pk", table_name=prefix)
    op.drop_index(f"ix_{prefix}_remote_revision_pk", table_name=prefix)
    op.drop_index(f"ix_{prefix}_local_revision_pk", table_name=prefix)


def _create_indexes(table: str) -> None:
    op.create_index(
        f"ix_{table}_local_revision_pk",
        table,
        ["local_revision_pk"],
        unique=False,
    )
    op.create_index(
        f"ix_{table}_remote_revision_pk",
        table,
        ["remote_revision_pk"],
        unique=False,
    )
    op.create_index(f"ix_{table}_page_link_pk", table, ["page_link_pk"], unique=False)
    op.execute(
        sa.text(
            f"CREATE UNIQUE INDEX uq_{table}_pair ON {table}"
            " (min(local_revision_pk, remote_revision_pk),"
            " max(local_revision_pk, remote_revision_pk))"
        )
    )


def upgrade() -> None:
    _drop_indexes("remotelink")
    op.rename_table("remotelink", "revisionlink")
    _create_indexes("revisionlink")


def downgrade() -> None:
    _drop_indexes("revisionlink")
    op.rename_table("revisionlink", "remotelink")
    _create_indexes("remotelink")
