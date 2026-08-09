"""page link: the pairing revision links hang off

Correspondence between *pages* was derived from the revision links. That could
not represent a pair with nothing linkable -- a diverged pair, or one whose
other side is unfetched -- which are exactly the pairs a reviewer needs to see,
and it recomputed pairings from titles, which a page move breaks.

Existing rows are backfilled rather than dropped: every RemoteLink names two
revisions, each of which names a page, so its pairing is recoverable. Links
sharing a pairing collapse onto one PageLink, which is the ladder they were
always meant to form.

Revision ID: e5c93a17b820
Revises: d3b8f7a21c94
Create Date: 2026-08-09 14:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5c93a17b820"
down_revision: str | None = "d3b8f7a21c94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pagelink",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("local_page_pk", sa.Integer(), nullable=False),
        sa.Column("remote_page_pk", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["local_page_pk"], ["page.pk"]),
        sa.ForeignKeyConstraint(["remote_page_pk"], ["page.pk"]),
        sa.PrimaryKeyConstraint("pk"),
    )
    op.create_index(
        op.f("ix_pagelink_local_page_pk"), "pagelink", ["local_page_pk"], unique=False
    )
    op.create_index(
        op.f("ix_pagelink_remote_page_pk"), "pagelink", ["remote_page_pk"], unique=False
    )
    # Unique on the unordered pair, as remotelink is: a pairing asserted the
    # other way round is the same pairing.
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_pagelink_pair ON pagelink"
            " (min(local_page_pk, remote_page_pk), max(local_page_pk, remote_page_pk))"
        )
    )

    op.add_column("remotelink", sa.Column("page_link_pk", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_remotelink_page_link_pk"),
        "remotelink",
        ["page_link_pk"],
        unique=False,
    )

    # Backfill: one PageLink per distinct unordered page pair behind the
    # existing links, keeping each link's own orientation as the pairing's.
    op.execute(sa.text("""
            INSERT INTO pagelink (local_page_pk, remote_page_pk, origin, created_at)
            SELECT local_page, remote_page, 'title_match', CURRENT_TIMESTAMP
            FROM (
                SELECT lr.page_pk AS local_page, rr.page_pk AS remote_page,
                       min(l.pk) AS first_link
                FROM remotelink l
                JOIN revision lr ON lr.pk = l.local_revision_pk
                JOIN revision rr ON rr.pk = l.remote_revision_pk
                GROUP BY min(lr.page_pk, rr.page_pk), max(lr.page_pk, rr.page_pk)
            )
            """))
    op.execute(sa.text("""
            UPDATE remotelink SET page_link_pk = (
                SELECT p.pk FROM pagelink p
                JOIN revision lr ON lr.pk = remotelink.local_revision_pk
                JOIN revision rr ON rr.pk = remotelink.remote_revision_pk
                WHERE min(p.local_page_pk, p.remote_page_pk)
                      = min(lr.page_pk, rr.page_pk)
                  AND max(p.local_page_pk, p.remote_page_pk)
                      = max(lr.page_pk, rr.page_pk)
            )
            """))


def downgrade() -> None:
    op.drop_index(op.f("ix_remotelink_page_link_pk"), table_name="remotelink")
    op.drop_column("remotelink", "page_link_pk")
    op.execute(sa.text("DROP INDEX IF EXISTS uq_pagelink_pair"))
    op.drop_index(op.f("ix_pagelink_remote_page_pk"), table_name="pagelink")
    op.drop_index(op.f("ix_pagelink_local_page_pk"), table_name="pagelink")
    op.drop_table("pagelink")
