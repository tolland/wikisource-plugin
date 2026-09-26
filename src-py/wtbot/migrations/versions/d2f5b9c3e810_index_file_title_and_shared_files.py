"""IndexMeta names its File: title; shared-repository descriptions go.

Revision ID: d2f5b9c3e810
Revises: c6a1e8d4f207
Create Date: 2026-09-26 18:00:00.000000+00:00

A Wikimedia wiki serves most scans from Commons. Its ``File:`` title there is
``missing`` and ``known``: the page, with real ids, is Commons's. Until now
the fetch borrowed that page's description text into a page row on the
local site, with no ids -- the one kind of page row with no revid. Commons is
now a registered site -- created at startup, without a credential, or here
if this migration needs it first -- and the page is fetched there.

- ``indexmeta.file_title_pk`` (NOT NULL, FK title) names the index's scan,
  wherever it lives. Filled in from what the database already knows: a
  shared-description row means Commons's title; otherwise the index's own
  site's ``File:`` title (created if missing), which the next fetch corrects
  if the file turns out to be shared.
- The shared-description page rows -- ``File:`` rows with text and no
  revid -- and their ``fileblob`` rows are deleted. **Refetch the index** (or
  the file) to fetch the page on Commons; the downloaded bytes stay on disk.
  Their local titles are marked fetched: we asked, and the wiki holds no page
  there.

Downgrade drops the column; the deleted rows are not recreated (a refetch on
the old code would).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2f5b9c3e810"
down_revision: str | None = "c6a1e8d4f207"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SHARED_DESCRIPTION = (
    "page.revid IS NULL AND page.text IS NOT NULL AND page.title LIKE 'File:%'"
)


def _commons_site(connection) -> int:
    row = connection.execute(
        sa.text("SELECT pk FROM site WHERE family = 'commons' AND code = 'commons'")
    ).first()
    if row is not None:
        return row[0]
    label_free = (
        connection.execute(
            sa.text("SELECT 1 FROM site WHERE label = 'commons'")
        ).first()
        is None
    )
    return connection.execute(
        sa.text(
            "INSERT INTO site (family, code, articlepath, label, created_at)"
            " VALUES ('commons', 'commons', '/wiki/$1', :label, CURRENT_TIMESTAMP)"
            " RETURNING pk"
        ),
        {"label": "commons" if label_free else None},
    ).scalar_one()


def _title(connection, site_pk: int, title: str) -> int:
    existing = connection.execute(
        sa.text("SELECT pk FROM title WHERE site_pk = :site AND title = :title"),
        {"site": site_pk, "title": title},
    ).first()
    if existing is not None:
        return existing[0]
    return connection.execute(
        sa.text(
            "INSERT INTO title (site_pk, title, expected_content_model)"
            " VALUES (:site, :title, 'wikitext') RETURNING pk"
        ),
        {"site": site_pk, "title": title},
    ).scalar_one()


def upgrade() -> None:
    connection = op.get_bind()

    file_titles: dict[int, int] = {}
    for index_pk, site_pk, index_title in connection.execute(
        sa.text(
            "SELECT m.title_pk, m.site_pk, t.title FROM indexmeta m"
            " JOIN title t ON t.pk = m.title_pk"
        )
    ).all():
        name = "File:" + index_title.partition(":")[2]
        shared = connection.execute(
            sa.text(
                "SELECT 1 FROM page JOIN title t ON t.pk = page.pk"
                f" WHERE t.site_pk = :site AND t.title = :name AND {_SHARED_DESCRIPTION}"
            ),
            {"site": site_pk, "name": name},
        ).first()
        file_titles[index_pk] = _title(
            connection, _commons_site(connection) if shared else site_pk, name
        )

    op.create_table(
        "_indexmeta_new",
        sa.Column("title_pk", sa.Integer(), nullable=False),
        sa.Column("site_pk", sa.Integer(), nullable=False),
        sa.Column("file_title_pk", sa.Integer(), nullable=False),
        sa.Column("short_name", sa.String(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("title_pk", name="pk_indexmeta"),
        sa.ForeignKeyConstraint(
            ["title_pk"], ["title.pk"], name="fk_indexmeta_title_pk_title"
        ),
        sa.ForeignKeyConstraint(
            ["site_pk"], ["site.pk"], name="fk_indexmeta_site_pk_site"
        ),
        sa.ForeignKeyConstraint(
            ["file_title_pk"], ["title.pk"], name="fk_indexmeta_file_title_pk_title"
        ),
        sa.UniqueConstraint("site_pk", "short_name", name="uq_indexmeta_site_short"),
    )
    for index_pk, file_title_pk in file_titles.items():
        connection.execute(
            sa.text(
                "INSERT INTO _indexmeta_new"
                " (title_pk, site_pk, file_title_pk, short_name, page_count)"
                " SELECT title_pk, site_pk, :file, short_name, page_count"
                " FROM indexmeta WHERE title_pk = :index"
            ),
            {"file": file_title_pk, "index": index_pk},
        )
    op.drop_table("indexmeta")
    op.rename_table("_indexmeta_new", "indexmeta")
    op.create_index("ix_indexmeta_site_pk", "indexmeta", ["site_pk"])
    op.create_index("ix_indexmeta_file_title_pk", "indexmeta", ["file_title_pk"])

    shared_pages = f"SELECT pk FROM page WHERE {_SHARED_DESCRIPTION}"
    op.execute(sa.text(f"DELETE FROM fileblob WHERE page_pk IN ({shared_pages})"))
    op.execute(
        sa.text(f"UPDATE title SET fetch_status = 'done' WHERE pk IN ({shared_pages})")
    )
    op.execute(sa.text(f"DELETE FROM page WHERE {_SHARED_DESCRIPTION}"))


def downgrade() -> None:
    op.create_table(
        "_indexmeta_old",
        sa.Column("title_pk", sa.Integer(), nullable=False),
        sa.Column("site_pk", sa.Integer(), nullable=False),
        sa.Column("short_name", sa.String(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("title_pk", name="pk_indexmeta"),
        sa.ForeignKeyConstraint(
            ["title_pk"], ["title.pk"], name="fk_indexmeta_title_pk_title"
        ),
        sa.ForeignKeyConstraint(
            ["site_pk"], ["site.pk"], name="fk_indexmeta_site_pk_site"
        ),
        sa.UniqueConstraint("site_pk", "short_name", name="uq_indexmeta_site_short"),
    )
    op.execute(sa.text("""
        INSERT INTO _indexmeta_old (title_pk, site_pk, short_name, page_count)
        SELECT title_pk, site_pk, short_name, page_count FROM indexmeta
        """))
    op.drop_table("indexmeta")
    op.rename_table("_indexmeta_old", "indexmeta")
    op.create_index("ix_indexmeta_site_pk", "indexmeta", ["site_pk"])
