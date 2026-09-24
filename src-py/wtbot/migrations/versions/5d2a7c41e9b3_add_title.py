"""Add Title, sharing its primary key with Page.

Revision ID: 5d2a7c41e9b3
Revises: 76940b0f1272
Create Date: 2026-09-24 10:00:00.000000+00:00

Step 1 of splitting Page into Title and WikiPage (docs/design/pages-and-existence.md).

Each existing page gets a title **with the same pk**. That is the whole trick:
every foreign key that points at ``page.pk`` today already holds a valid
``title.pk``, so later steps repoint constraints without touching data.

``expected_content_model`` is copied from ``page.content_model`` where the page
has one -- for a fetched page that is what the wiki said; for a fan-out
placeholder it is the model the fan-out assigned. Where it is null, the guess
is MediaWiki's own fallback, ``wikitext``: a namespace cannot decide it (see
the namespace-roles migration), and the next fetch corrects a wrong guess.

Adding the foreign key rebuilds ``page``, which nearly every other table
references. That works because ``wtbot.db.migration_connection`` runs
migrations with foreign keys off and checks them over the finished state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5d2a7c41e9b3"
down_revision: str | None = "76940b0f1272"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "title",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("site_pk", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("expected_content_model", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["site_pk"], ["site.pk"], name="fk_title_site_pk_site"),
        sa.PrimaryKeyConstraint("pk", name="pk_title"),
        sa.UniqueConstraint("site_pk", "title", name="uq_title_site_pk"),
    )
    op.create_index("ix_title_site_pk", "title", ["site_pk"])

    op.execute(sa.text("""
        INSERT INTO title (pk, site_pk, title, expected_content_model)
        SELECT pk, site_pk, title, COALESCE(content_model, 'wikitext')
        FROM page
        """))

    with op.batch_alter_table("page") as batch_op:
        batch_op.create_foreign_key("fk_page_pk_title", "title", ["pk"], ["pk"])


def downgrade() -> None:
    with op.batch_alter_table("page") as batch_op:
        batch_op.drop_constraint("fk_page_pk_title", type_="foreignkey")
    op.drop_index("ix_title_site_pk", table_name="title")
    op.drop_table("title")
