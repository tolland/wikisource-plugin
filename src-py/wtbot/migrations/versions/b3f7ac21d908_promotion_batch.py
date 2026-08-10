"""promotion + promotionbatch: the reviewable push queue

TODO item 6. The push queue is mutable, reviewable and cancellable, so it is
its own pair of tables rather than a status column on an audit log (discussion
§12) and rather than `EditJournal` + the commit worker (§7): the journal is the
*local per-save* transaction log, and cross-site intent has a different
lifecycle -- proposed, reviewed, possibly abandoned, then written.

Two tables for two lifetimes. A batch is a run (this work, this direction, this
approval); a promotion is one page inside it, with its own outcome, because a
batch that half-succeeds is the normal case and each row has to say which half
it was in.

Nothing is backfilled: there is no earlier representation of this to convert.

Revision ID: b3f7ac21d908
Revises: a7e2c58b4f10
Create Date: 2026-08-10 09:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3f7ac21d908"
down_revision: str | None = "a7e2c58b4f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "promotionbatch",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("source_site_pk", sa.Integer(), nullable=False),
        sa.Column("target_site_pk", sa.Integer(), nullable=False),
        sa.Column("index_link_pk", sa.Integer(), nullable=True),
        sa.Column("source_index_title", sa.String(), nullable=False),
        sa.Column("target_index_title", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_site_pk"], ["site.pk"]),
        sa.ForeignKeyConstraint(["target_site_pk"], ["site.pk"]),
        sa.ForeignKeyConstraint(["index_link_pk"], ["indexlink.pk"]),
        sa.PrimaryKeyConstraint("pk"),
    )
    for column in ("source_site_pk", "target_site_pk", "index_link_pk", "status"):
        op.create_index(op.f(f"ix_promotionbatch_{column}"), "promotionbatch", [column])

    op.create_table(
        "promotion",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("batch_pk", sa.Integer(), nullable=False),
        sa.Column("page_link_pk", sa.Integer(), nullable=True),
        sa.Column("source_page_pk", sa.Integer(), nullable=False),
        sa.Column("target_page_pk", sa.Integer(), nullable=True),
        sa.Column("target_title", sa.String(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("intent", sa.String(), nullable=False),
        sa.Column("source_revision_pk", sa.Integer(), nullable=False),
        sa.Column("anchor_link_pk", sa.Integer(), nullable=True),
        sa.Column("base_revid", sa.Integer(), nullable=True),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("comment", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("pre_push_target_revid", sa.Integer(), nullable=True),
        sa.Column("result_revid", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("staged_at", sa.DateTime(), nullable=False),
        sa.Column("pushed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["batch_pk"], ["promotionbatch.pk"]),
        sa.ForeignKeyConstraint(["page_link_pk"], ["pagelink.pk"]),
        sa.ForeignKeyConstraint(["source_page_pk"], ["page.pk"]),
        sa.ForeignKeyConstraint(["target_page_pk"], ["page.pk"]),
        sa.ForeignKeyConstraint(["source_revision_pk"], ["revision.pk"]),
        sa.ForeignKeyConstraint(["anchor_link_pk"], ["remotelink.pk"]),
        sa.PrimaryKeyConstraint("pk"),
    )
    for column in (
        "batch_pk",
        "page_link_pk",
        "source_page_pk",
        "target_page_pk",
        "anchor_link_pk",
        "status",
    ):
        op.create_index(op.f(f"ix_promotion_{column}"), "promotion", [column])


def downgrade() -> None:
    op.drop_table("promotion")
    op.drop_table("promotionbatch")
