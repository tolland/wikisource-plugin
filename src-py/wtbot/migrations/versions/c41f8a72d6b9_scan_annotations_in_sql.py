"""scan annotations in sql

Bounding boxes move from per-page SVG documents into the new
``scanannotation`` table (with an OCR category per box), and
``annotationanchor`` is renamed to ``texttargetanchor`` to reflect its
purpose: anchoring ranges of text documents that are targets for OCR or
other processed text.

Revision ID: c41f8a72d6b9
Revises: 9b4e2f61a3c7
Create Date: 2026-07-20 00:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "c41f8a72d6b9"
down_revision: str | None = "9b4e2f61a3c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATEGORY = sa.Enum(
    "header",
    "footer",
    "body",
    "paragraph",
    "section",
    "ignore",
    name="annotationcategory",
)


def upgrade() -> None:
    op.drop_index(
        op.f("ix_annotationanchor_annotation_id"), table_name="annotationanchor"
    )
    op.drop_index(op.f("ix_annotationanchor_page_pk"), table_name="annotationanchor")
    op.rename_table("annotationanchor", "texttargetanchor")
    with op.batch_alter_table("texttargetanchor") as batch:
        batch.drop_constraint("uq_anchor_page_annotation", type_="unique")
        batch.create_unique_constraint(
            "uq_text_target_anchor_page_annotation", ["page_pk", "annotation_id"]
        )
    op.create_index(
        op.f("ix_texttargetanchor_annotation_id"),
        "texttargetanchor",
        ["annotation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_texttargetanchor_page_pk"),
        "texttargetanchor",
        ["page_pk"],
        unique=False,
    )

    op.create_table(
        "scanannotation",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("page_pk", sa.Integer(), nullable=False),
        sa.Column("annotation_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("width", sa.Float(), nullable=False),
        sa.Column("height", sa.Float(), nullable=False),
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("category", CATEGORY, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["page_pk"],
            ["page.pk"],
        ),
        sa.PrimaryKeyConstraint("pk"),
        sa.UniqueConstraint(
            "page_pk", "annotation_id", name="uq_scan_annotation_page_annotation"
        ),
    )
    op.create_index(
        op.f("ix_scanannotation_annotation_id"),
        "scanannotation",
        ["annotation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scanannotation_page_pk"),
        "scanannotation",
        ["page_pk"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_scanannotation_page_pk"), table_name="scanannotation")
    op.drop_index(op.f("ix_scanannotation_annotation_id"), table_name="scanannotation")
    op.drop_table("scanannotation")

    op.drop_index(op.f("ix_texttargetanchor_page_pk"), table_name="texttargetanchor")
    op.drop_index(
        op.f("ix_texttargetanchor_annotation_id"), table_name="texttargetanchor"
    )
    with op.batch_alter_table("texttargetanchor") as batch:
        batch.drop_constraint("uq_text_target_anchor_page_annotation", type_="unique")
        batch.create_unique_constraint(
            "uq_anchor_page_annotation", ["page_pk", "annotation_id"]
        )
    op.rename_table("texttargetanchor", "annotationanchor")
    op.create_index(
        op.f("ix_annotationanchor_annotation_id"),
        "annotationanchor",
        ["annotation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_annotationanchor_page_pk"),
        "annotationanchor",
        ["page_pk"],
        unique=False,
    )
