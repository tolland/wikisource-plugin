"""ocr backend config, scope-based

Recreates ``ocrbackendconfig`` (dropped in the previous migration along
with its Site foreign key) with a plain ``scope`` string column instead:
a config row no longer requires a Site to exist, so the OCR client/API
logic that queries this table (src-py/ocrapi) doesn't need to know what a
"wiki" is, even though the row class itself stays part of wtbot's own
schema (see wtbot.model.ocr_backend).

Revision ID: c9d21f6a4b5e
Revises: b81f4c0d9e23
Create Date: 2026-07-29 00:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "c9d21f6a4b5e"
down_revision: str | None = "b81f4c0d9e23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KIND = sa.Enum("wikimedia", "token_api", name="ocrbackendkind")


def upgrade() -> None:
    op.create_table(
        "ocrbackendconfig",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("scope", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
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
        sa.PrimaryKeyConstraint("pk"),
        sa.UniqueConstraint("scope", "name", name="uq_ocr_backend_scope_name"),
    )
    op.create_index(
        op.f("ix_ocrbackendconfig_scope"),
        "ocrbackendconfig",
        ["scope"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ocrbackendconfig_scope"), table_name="ocrbackendconfig")
    op.drop_table("ocrbackendconfig")
