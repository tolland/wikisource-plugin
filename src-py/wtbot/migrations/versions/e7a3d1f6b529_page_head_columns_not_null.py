"""A page's head columns are NOT NULL.

Revision ID: e7a3d1f6b529
Revises: d2f5b9c3e810
Create Date: 2026-09-29 10:00:00.000000+00:00

Step 3b of the Title/WikiPage split. A page row exists only where the wiki
holds the page (3a), and the one kind of held page with no local ids -- the
borrowed shared-repository description -- is gone (d2f5b9c3e810). So every
row has what a held page has: ``pageid``, ``revid``, ``remote_timestamp``,
``text`` and ``content_model``.

Two of them can be derived where an older fetch left them empty:
``content_model`` from the title (which the fetch keeps equal to the wiki's
answer), ``remote_timestamp`` from the head revision. Anything still empty
stops the migration, naming the rows: refetch them and migrate again.

``contributor`` and ``comment`` stay nullable -- a revision-deleted user or
summary is a real state -- as do ``latest_revision_pk`` and
``history_complete_from_revid``, which say what our revision store holds.

The table is rebuilt by hand: SQLite cannot change a column's nullability in
place.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7a3d1f6b529"
down_revision: str | None = "d2f5b9c3e810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HEAD = ("pageid", "revid", "remote_timestamp", "text", "content_model")
_COLUMNS = (
    "pk, site_pk, title, content_model, pageid, revid, remote_timestamp,"
    " contributor, comment, text, latest_revision_pk, history_complete_from_revid"
)


def _page(name: str, *, required: bool) -> None:
    op.create_table(
        name,
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("site_pk", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content_model", sa.String(), nullable=not required),
        sa.Column("pageid", sa.Integer(), nullable=not required),
        sa.Column("revid", sa.Integer(), nullable=not required),
        sa.Column("remote_timestamp", sa.DateTime(), nullable=not required),
        sa.Column("contributor", sa.String(), nullable=True),
        sa.Column("comment", sa.String(), nullable=True),
        sa.Column("text", sa.String(), nullable=not required),
        sa.Column("latest_revision_pk", sa.Integer(), nullable=True),
        sa.Column("history_complete_from_revid", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("pk", name="pk_page"),
        sa.UniqueConstraint("site_pk", "title", name="uq_page_site_title"),
        sa.ForeignKeyConstraint(["site_pk"], ["site.pk"], name="fk_page_site_pk_site"),
        sa.ForeignKeyConstraint(["pk"], ["title.pk"], name="fk_page_pk_title"),
    )


def _rebuild(*, required: bool) -> None:
    _page("_page_new", required=required)
    op.execute(
        sa.text(f"INSERT INTO _page_new ({_COLUMNS}) SELECT {_COLUMNS} FROM page")
    )
    op.drop_table("page")
    op.rename_table("_page_new", "page")


def upgrade() -> None:
    op.execute(sa.text("""
        UPDATE page SET content_model = (
            SELECT expected_content_model FROM title WHERE title.pk = page.pk
        ) WHERE content_model IS NULL
        """))
    op.execute(sa.text("""
        UPDATE page SET remote_timestamp = (
            SELECT timestamp FROM revision WHERE revision.pk = page.latest_revision_pk
        ) WHERE remote_timestamp IS NULL
        """))
    missing = " OR ".join(f"{column} IS NULL" for column in _HEAD)
    incomplete = (
        op.get_bind()
        .execute(sa.text(f"SELECT pk, title FROM page WHERE {missing} ORDER BY pk"))
        .all()
    )
    if incomplete:
        listed = ", ".join(f"{pk} {title!r}" for pk, title in incomplete)
        raise RuntimeError(
            "page rows are missing a head column (pageid, revid, "
            f"remote_timestamp, text or content_model): {listed}. Refetch them "
            "and migrate again."
        )
    _rebuild(required=True)


def downgrade() -> None:
    _rebuild(required=False)
