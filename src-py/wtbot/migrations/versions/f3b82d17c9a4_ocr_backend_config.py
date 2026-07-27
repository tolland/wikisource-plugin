"""per-site OCR backend config

New ``ocrbackendconfig`` table: each Site's OCR API endpoints (Wikimedia
OCR instance or a token-guarded vision API) plus the metadata needed to
talk to them — token, default engine/langs, default prompt.

Revision ID: f3b82d17c9a4
Revises: e7a91c54b2d8
Create Date: 2026-07-27 00:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "f3b82d17c9a4"
down_revision: str | None = "e7a91c54b2d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KIND = sa.Enum("wikimedia", "token_api", name="ocrbackendkind")


def upgrade() -> None:
    op.create_table(
        "ocrbackendconfig",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("site_pk", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("kind", KIND, nullable=False),
        sa.Column("base_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("api_token", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("default_engine", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("default_langs", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("default_prompt", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["site_pk"],
            ["site.pk"],
        ),
        sa.PrimaryKeyConstraint("pk"),
        sa.UniqueConstraint("site_pk", "name", name="uq_ocr_backend_site_name"),
    )
    op.create_index(
        op.f("ix_ocrbackendconfig_site_pk"),
        "ocrbackendconfig",
        ["site_pk"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ocrbackendconfig_site_pk"), table_name="ocrbackendconfig")
    op.drop_table("ocrbackendconfig")
