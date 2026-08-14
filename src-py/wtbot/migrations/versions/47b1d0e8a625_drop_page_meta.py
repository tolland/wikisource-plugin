"""drop superseded PageMeta

Revision ID: 47b1d0e8a625
Revises: 2f6a8c1d9e40
Create Date: 2026-08-14 12:30:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "47b1d0e8a625"
down_revision: str | None = "2f6a8c1d9e40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_pagemeta_page_pk"), table_name="pagemeta")
    op.drop_index(op.f("ix_pagemeta_index_title"), table_name="pagemeta")
    op.drop_table("pagemeta")


def downgrade() -> None:
    op.create_table(
        "pagemeta",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("page_pk", sa.Integer(), nullable=False),
        sa.Column("index_title", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("quality_level", sa.Integer(), nullable=True),
        sa.Column(
            "source_image_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.Column("default_body", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("thumb_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("thumb_width", sa.Integer(), nullable=True),
        sa.Column("thumb_height", sa.Integer(), nullable=True),
        sa.Column("raster_path", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("thumb_path", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["page_pk"], ["page.pk"]),
        sa.PrimaryKeyConstraint("pk"),
        sa.UniqueConstraint("page_pk", name="uq_pagemeta_page"),
    )
    op.create_index(
        op.f("ix_pagemeta_index_title"),
        "pagemeta",
        ["index_title"],
        unique=False,
    )
    op.create_index(op.f("ix_pagemeta_page_pk"), "pagemeta", ["page_pk"], unique=False)
    op.execute(
        sa.text(
            "INSERT INTO pagemeta"
            " (page_pk, index_title, page_number, quality_level, source_image_url,"
            " default_body, thumb_url, thumb_width, thumb_height, raster_path, thumb_path)"
            " SELECT m.page_pk, i.title, m.page_number, m.quality_level,"
            " m.source_image_url, m.default_body, m.thumb_url, m.thumb_width,"
            " m.thumb_height, m.raster_path, m.thumb_path"
            " FROM proofreadpagemeta m JOIN page i ON i.pk = m.index_page_pk"
        )
    )
