"""index link: the work-level correspondence the viewer opens on

For Wikisource the unit of comparison is the Index, not the page: pages are
compared and promoted *within* a work, and "is this work tracked against
upstream?" is the question asked first. Answering it meant working backwards
from ``pagelink`` rows through ``pagemeta.index_title``, which is a title match
in a model that is otherwise careful never to key on titles.

``indexlink`` is a side table on ``pagelink``, the way ``indexmeta`` is a side
table on ``page``: an ``Index:`` page is a page, so the pairing of two of them
is already a ``PageLink`` -- with its own ladder over the index bodies, which
diverge like any other. What is added is the statement that this pairing is a
work, and ``pagelink.index_link_pk`` so a work's page pairs are a join.

Nothing is backfilled. The pointer can only be set once a work exists, and no
work exists until someone links one; ``index_link_store.adopt_children`` claims
the pairs already present at that moment, so a database that has been running
``pair-index`` loses nothing by this being empty.

Revision ID: a7e2c58b4f10
Revises: f1a6d94c30be
Create Date: 2026-08-09 18:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7e2c58b4f10"
down_revision: str | None = "f1a6d94c30be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "indexlink",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("page_link_pk", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["page_link_pk"], ["pagelink.pk"]),
        sa.PrimaryKeyConstraint("pk"),
    )
    # Unique, not merely indexed: one work per pairing. Two IndexLink rows on
    # one PageLink would be two identities for one work, and every count the
    # viewer renders would double.
    op.create_index(
        op.f("ix_indexlink_page_link_pk"), "indexlink", ["page_link_pk"], unique=True
    )

    # Plain add_column, not batch mode: SQLite's batch rebuild would DROP
    # `pagelink`, which `remotelink` references under PRAGMA foreign_keys=ON.
    op.add_column("pagelink", sa.Column("index_link_pk", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_pagelink_index_link_pk"), "pagelink", ["index_link_pk"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_pagelink_index_link_pk"), table_name="pagelink")
    op.drop_column("pagelink", "index_link_pk")
    op.drop_index(op.f("ix_indexlink_page_link_pk"), table_name="indexlink")
    op.drop_table("indexlink")
