"""IndexMeta shares its Index's title key; PageLink's two sides reference title.

Revision ID: a9d4b7e1f026
Revises: f8c0a6e2d493
Create Date: 2026-09-25 11:00:00.000000+00:00

Both are about addresses:

- **IndexMeta** is curated metadata for an ``Index:`` (its short name, page
  count). Keyed to the title, with the title's pk as its own primary key, so an
  Index being assembled from the client can carry it before any wiki holds the
  Index. The surrogate ``pk`` and the ``page_pk`` reference collapse into
  ``title_pk``; ``uq_indexmeta_page`` and ``ix_indexmeta_page_pk`` go with them,
  since a primary key is already unique and indexed.
- **PageLink** records the intention to keep two addresses in step, whether or
  not either exists on its wiki yet, so ``local_page_pk``/``remote_page_pk``
  now reference ``title``. The column names stay (they are left for the
  directed-links rework).

**No data moves**: every page pk already is its title's pk.

Both tables are rebuilt by hand, not by batch mode: ``pagelink`` carries
``uq_pagelink_pair``, an expression index batch mode cannot reflect and would
silently drop, and ``indexmeta`` changes its primary key.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9d4b7e1f026"
down_revision: str | None = "f8c0a6e2d493"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _pagelink(name: str, target: str) -> None:
    op.create_table(
        name,
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("local_page_pk", sa.Integer(), nullable=False),
        sa.Column("remote_page_pk", sa.Integer(), nullable=False),
        sa.Column(
            "origin",
            sa.Enum("copy", "title_match", "manual", "reconciled", name="linkorigin"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("pk", name="pk_pagelink"),
        sa.ForeignKeyConstraint(
            ["local_page_pk"],
            [f"{target}.pk"],
            name=f"fk_pagelink_local_page_pk_{target}",
        ),
        sa.ForeignKeyConstraint(
            ["remote_page_pk"],
            [f"{target}.pk"],
            name=f"fk_pagelink_remote_page_pk_{target}",
        ),
    )


def _rebuild_pagelink(target: str) -> None:
    _pagelink("_pagelink_new", target)
    op.execute(sa.text("""
        INSERT INTO _pagelink_new (pk, local_page_pk, remote_page_pk, origin, created_at)
        SELECT pk, local_page_pk, remote_page_pk, origin, created_at FROM pagelink
        """))
    op.drop_table("pagelink")
    op.rename_table("_pagelink_new", "pagelink")
    op.create_index("ix_pagelink_local_page_pk", "pagelink", ["local_page_pk"])
    op.create_index("ix_pagelink_remote_page_pk", "pagelink", ["remote_page_pk"])
    # Unique on the unordered pair. Restated by hand: it cannot be reflected.
    op.create_index(
        "uq_pagelink_pair",
        "pagelink",
        [
            sa.text("min(local_page_pk, remote_page_pk)"),
            sa.text("max(local_page_pk, remote_page_pk)"),
        ],
        unique=True,
    )


def upgrade() -> None:
    op.create_table(
        "_indexmeta_new",
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
        INSERT INTO _indexmeta_new (title_pk, site_pk, short_name, page_count)
        SELECT page_pk, site_pk, short_name, page_count FROM indexmeta
        """))
    op.drop_table("indexmeta")
    op.rename_table("_indexmeta_new", "indexmeta")
    op.create_index("ix_indexmeta_site_pk", "indexmeta", ["site_pk"])

    _rebuild_pagelink("title")


def downgrade() -> None:
    _rebuild_pagelink("page")

    # The surrogate pk comes back as a fresh number per row; nothing referenced
    # it, so any number will do.
    op.create_table(
        "_indexmeta_old",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("page_pk", sa.Integer(), nullable=False),
        sa.Column("site_pk", sa.Integer(), nullable=False),
        sa.Column("short_name", sa.String(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("pk", name="pk_indexmeta"),
        sa.ForeignKeyConstraint(
            ["page_pk"], ["page.pk"], name="fk_indexmeta_page_pk_page"
        ),
        sa.ForeignKeyConstraint(
            ["site_pk"], ["site.pk"], name="fk_indexmeta_site_pk_site"
        ),
        sa.UniqueConstraint("page_pk", name="uq_indexmeta_page"),
        sa.UniqueConstraint("site_pk", "short_name", name="uq_indexmeta_site_short"),
    )
    op.execute(sa.text("""
        INSERT INTO _indexmeta_old (page_pk, site_pk, short_name, page_count)
        SELECT title_pk, site_pk, short_name, page_count FROM indexmeta
        """))
    op.drop_table("indexmeta")
    op.rename_table("_indexmeta_old", "indexmeta")
    op.create_index("ix_indexmeta_page_pk", "indexmeta", ["page_pk"])
    op.create_index("ix_indexmeta_site_pk", "indexmeta", ["site_pk"])
