"""box→range links

New ``boxrangelink`` table: an explicit link from a scan bounding box to
the text target range its content is destined for, replacing the implicit
convention of a box and its anchor sharing one annotation id. One link per
box (unique on page_pk + box_annotation_id).

Revision ID: e7a91c54b2d8
Revises: c41f8a72d6b9
Create Date: 2026-07-27 00:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "e7a91c54b2d8"
down_revision: str | None = "c41f8a72d6b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "boxrangelink",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("page_pk", sa.Integer(), nullable=False),
        sa.Column(
            "box_annotation_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column(
            "range_annotation_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["page_pk"],
            ["page.pk"],
        ),
        sa.PrimaryKeyConstraint("pk"),
        sa.UniqueConstraint(
            "page_pk", "box_annotation_id", name="uq_box_range_link_box"
        ),
    )
    op.create_index(
        op.f("ix_boxrangelink_box_annotation_id"),
        "boxrangelink",
        ["box_annotation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_boxrangelink_range_annotation_id"),
        "boxrangelink",
        ["range_annotation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_boxrangelink_page_pk"),
        "boxrangelink",
        ["page_pk"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_boxrangelink_page_pk"), table_name="boxrangelink")
    op.drop_index(
        op.f("ix_boxrangelink_range_annotation_id"), table_name="boxrangelink"
    )
    op.drop_index(op.f("ix_boxrangelink_box_annotation_id"), table_name="boxrangelink")
    op.drop_table("boxrangelink")
