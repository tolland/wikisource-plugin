"""revision store: content, revision, slot

Adds the page -> revision -> slot -> content chain, mirroring MediaWiki's own
schema (see docs/upstream-sync-TODO.md section 4.5).

Purely additive: no existing table is dropped or rewritten, so every ``page.pk``
survives and the eleven tables that reference it (annotations, box range links,
text target anchors, page/index/file meta, file blobs, transclusions, commits,
edit journal) keep their rows. ``page.text``/``revid``/``sha1`` stay as the head
denormalisation, so existing readers are untouched while the revision store
fills in behind them.

Revision ID: d4a7b1e6c5f2
Revises: c9d21f6a4b5e
Create Date: 2026-07-29 05:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4a7b1e6c5f2"
down_revision: str | None = "c9d21f6a4b5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("content_sha1", sa.String(), nullable=False),
        sa.Column("content_model", sa.String(), nullable=True),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("remote_sha1", sa.String(), nullable=True),
        sa.Column("remote_size", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("pk"),
        sa.UniqueConstraint(
            "content_sha1", "content_model", name="uq_content_sha1_model"
        ),
    )
    op.create_index(
        op.f("ix_content_content_sha1"), "content", ["content_sha1"], unique=False
    )

    op.create_table(
        "revision",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("page_pk", sa.Integer(), nullable=False),
        sa.Column("revid", sa.Integer(), nullable=False),
        sa.Column("parent_revid", sa.Integer(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("contributor", sa.String(), nullable=True),
        sa.Column("comment", sa.String(), nullable=True),
        sa.Column("minor", sa.Boolean(), nullable=False),
        sa.Column("remote_sha1", sa.String(), nullable=True),
        sa.Column("remote_size", sa.Integer(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["page_pk"], ["page.pk"]),
        sa.PrimaryKeyConstraint("pk"),
        sa.UniqueConstraint("page_pk", "revid", name="uq_revision_page_revid"),
    )
    op.create_index(op.f("ix_revision_page_pk"), "revision", ["page_pk"], unique=False)
    op.create_index(op.f("ix_revision_revid"), "revision", ["revid"], unique=False)

    op.create_table(
        "slot",
        sa.Column("revision_pk", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content_pk", sa.Integer(), nullable=False),
        sa.Column("origin_revid", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["content_pk"], ["content.pk"]),
        sa.ForeignKeyConstraint(["revision_pk"], ["revision.pk"]),
        sa.PrimaryKeyConstraint("revision_pk", "role"),
    )
    op.create_index(op.f("ix_slot_content_pk"), "slot", ["content_pk"], unique=False)

    # SQLite cannot add a column with an inline REFERENCES clause, and batch
    # mode would rewrite `page` -- which is exactly what must not happen, since
    # a rewrite would renumber nothing but does re-create every FK into it.
    # Plain nullable columns keep this additive; the relationship is enforced in
    # the model layer.
    with op.batch_alter_table("page", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("latest_revision_pk", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("history_complete_from_revid", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("page", schema=None) as batch_op:
        batch_op.drop_column("history_complete_from_revid")
        batch_op.drop_column("latest_revision_pk")

    op.drop_index(op.f("ix_slot_content_pk"), table_name="slot")
    op.drop_table("slot")
    op.drop_index(op.f("ix_revision_revid"), table_name="revision")
    op.drop_index(op.f("ix_revision_page_pk"), table_name="revision")
    op.drop_table("revision")
    op.drop_index(op.f("ix_content_content_sha1"), table_name="content")
    op.drop_table("content")
