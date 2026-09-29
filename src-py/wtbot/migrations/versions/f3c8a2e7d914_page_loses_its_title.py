"""A page has no name of its own: page.title goes.

Revision ID: f3c8a2e7d914
Revises: e7a3d1f6b529
Create Date: 2026-09-29 14:00:00.000000+00:00

Step 3c of the Title/WikiPage split. ``page.title`` mirrored ``title.title``
for the page at that address -- the two share a pk -- and was written once,
by the transition hook that kept every page a title. The hook is gone; the
name is the title's alone, and ``uq_page_site_title`` with it (``title``
keeps ``(site_pk, title)`` unique).

No data moves. Rebuilt by hand, as SQLite cannot drop a column that a
constraint names. Downgrade restores the column from ``title``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3c8a2e7d914"
down_revision: str | None = "e7a3d1f6b529"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEPT = (
    "pk, site_pk, content_model, pageid, revid, remote_timestamp,"
    " contributor, comment, text, latest_revision_pk, history_complete_from_revid"
)


def _page(name: str, *, with_title: bool) -> None:
    columns = [
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("site_pk", sa.Integer(), nullable=False),
    ]
    if with_title:
        columns.append(sa.Column("title", sa.String(), nullable=False))
    columns += [
        sa.Column("content_model", sa.String(), nullable=False),
        sa.Column("pageid", sa.Integer(), nullable=False),
        sa.Column("revid", sa.Integer(), nullable=False),
        sa.Column("remote_timestamp", sa.DateTime(), nullable=False),
        sa.Column("contributor", sa.String(), nullable=True),
        sa.Column("comment", sa.String(), nullable=True),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("latest_revision_pk", sa.Integer(), nullable=True),
        sa.Column("history_complete_from_revid", sa.Integer(), nullable=True),
    ]
    constraints = [
        sa.PrimaryKeyConstraint("pk", name="pk_page"),
        sa.ForeignKeyConstraint(["site_pk"], ["site.pk"], name="fk_page_site_pk_site"),
        sa.ForeignKeyConstraint(["pk"], ["title.pk"], name="fk_page_pk_title"),
    ]
    if with_title:
        constraints.append(
            sa.UniqueConstraint("site_pk", "title", name="uq_page_site_title")
        )
    op.create_table(name, *columns, *constraints)


def upgrade() -> None:
    _page("_page_new", with_title=False)
    op.execute(sa.text(f"INSERT INTO _page_new ({_KEPT}) SELECT {_KEPT} FROM page"))
    op.drop_table("page")
    op.rename_table("_page_new", "page")


def downgrade() -> None:
    _page("_page_old", with_title=True)
    op.execute(sa.text(f"""
        INSERT INTO _page_old (title, {_KEPT})
        SELECT title.title, {', '.join(f'page.{c.strip()}' for c in _KEPT.split(','))}
        FROM page JOIN title ON title.pk = page.pk
        """))
    op.drop_table("page")
    op.rename_table("_page_old", "page")
