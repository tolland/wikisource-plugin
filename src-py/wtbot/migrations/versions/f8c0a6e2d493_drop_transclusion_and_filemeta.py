"""Drop Transclusion and FileMeta.

Revision ID: f8c0a6e2d493
Revises: e5f2a8d1c349
Create Date: 2026-09-25 10:00:00.000000+00:00

Both hung off ``page`` and both are about to be rethought rather than moved:

- **Transclusion** was never populated -- nothing wrote a row. Its shape is
  recorded in docs/design/pages-and-existence.md for when composed works are
  taken up (``FetchKind.transclusion`` still names the fetch it was meant to
  support).
- **FileMeta** held provenance for ``File:`` pages (origin, crop geometry on
  the source scan). Image-specific file attributes need designing properly,
  particularly for files created from the client before any fetch; its shape
  is recorded in the same place.

**Rows in either table are discarded.** Dump first if a dev database holds
FileMeta rows worth keeping (``wtbot.maintenance.dump``); restoring such a
dump into this schema drops the two tables rather than refusing the dump.

Downgrade recreates both tables, empty, in their original shape.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8c0a6e2d493"
down_revision: str | None = "e5f2a8d1c349"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("transclusion")  # takes ix_transclusion_index_title with it
    op.drop_table("filemeta")  # and ix_filemeta_page_pk


def downgrade() -> None:
    op.create_table(
        "filemeta",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("page_pk", sa.Integer(), nullable=False),
        sa.Column(
            "origin",
            sa.Enum("remote", "paste", "ocr", name="fileorigin"),
            nullable=False,
        ),
        sa.Column("source_page_pk", sa.Integer(), nullable=True),
        sa.Column("source_page_number", sa.Integer(), nullable=True),
        sa.Column("crop_x", sa.Integer(), nullable=True),
        sa.Column("crop_y", sa.Integer(), nullable=True),
        sa.Column("crop_w", sa.Integer(), nullable=True),
        sa.Column("crop_h", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["page_pk"], ["page.pk"], name="fk_filemeta_page_pk_page"
        ),
        sa.ForeignKeyConstraint(
            ["source_page_pk"], ["page.pk"], name="fk_filemeta_source_page_pk_page"
        ),
        sa.PrimaryKeyConstraint("pk", name="pk_filemeta"),
        sa.UniqueConstraint("page_pk", name="uq_filemeta_page"),
    )
    op.create_index("ix_filemeta_page_pk", "filemeta", ["page_pk"])

    op.create_table(
        "transclusion",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("site_pk", sa.Integer(), nullable=False),
        sa.Column("source_page_pk", sa.Integer(), nullable=False),
        sa.Column("index_title", sa.String(), nullable=False),
        sa.Column("from_page", sa.Integer(), nullable=False),
        sa.Column("to_page", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["site_pk"], ["site.pk"], name="fk_transclusion_site_pk_site"
        ),
        sa.ForeignKeyConstraint(
            ["source_page_pk"], ["page.pk"], name="fk_transclusion_source_page_pk_page"
        ),
        sa.PrimaryKeyConstraint("pk", name="pk_transclusion"),
    )
    op.create_index("ix_transclusion_index_title", "transclusion", ["index_title"])
