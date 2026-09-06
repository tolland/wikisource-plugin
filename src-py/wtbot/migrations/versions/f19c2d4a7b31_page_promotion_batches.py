"""Make a promotion batch one page and a promotion one revision.

Revision ID: f19c2d4a7b31
Revises: e7f3b415fd0a
Create Date: 2026-08-15 12:00:00+00:00
"""

from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import RowMapping

revision: str = "f19c2d4a7b31"
down_revision: str | None = "e7f3b415fd0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_page_batch_table(name: str) -> None:
    op.create_table(
        name,
        sa.Column("pk", sa.Integer(), primary_key=True),
        sa.Column("source_site_pk", sa.Integer(), nullable=False),
        sa.Column("target_site_pk", sa.Integer(), nullable=False),
        sa.Column("index_link_pk", sa.Integer(), nullable=True),
        sa.Column("page_link_pk", sa.Integer(), nullable=True),
        sa.Column("source_page_pk", sa.Integer(), nullable=False),
        sa.Column("target_page_pk", sa.Integer(), nullable=True),
        sa.Column("source_title", sa.String(), nullable=False),
        sa.Column("target_title", sa.String(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("source_head_revid", sa.Integer(), nullable=True),
        sa.Column("anchor_link_pk", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_site_pk"], ["site.pk"]),
        sa.ForeignKeyConstraint(["target_site_pk"], ["site.pk"]),
        sa.ForeignKeyConstraint(["index_link_pk"], ["indexlink.pk"]),
        sa.ForeignKeyConstraint(["page_link_pk"], ["pagelink.pk"]),
        sa.ForeignKeyConstraint(["source_page_pk"], ["page.pk"]),
        sa.ForeignKeyConstraint(["target_page_pk"], ["page.pk"]),
        sa.ForeignKeyConstraint(["anchor_link_pk"], ["revisionlink.pk"]),
    )


def _create_revision_promotion_table(name: str, batch_table: str) -> None:
    op.create_table(
        name,
        sa.Column("pk", sa.Integer(), primary_key=True),
        sa.Column("batch_pk", sa.Integer(), nullable=False),
        sa.Column("intent", sa.String(), nullable=False),
        sa.Column("source_revision_pk", sa.Integer(), nullable=False),
        sa.Column("predecessor_promotion_pk", sa.Integer(), nullable=True),
        sa.Column("base_revid", sa.Integer(), nullable=True),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("comment", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("pre_push_target_revid", sa.Integer(), nullable=True),
        sa.Column("result_revid", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("staged_at", sa.DateTime(), nullable=False),
        sa.Column("pushed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["batch_pk"], [f"{batch_table}.pk"]),
        sa.ForeignKeyConstraint(["source_revision_pk"], ["revision.pk"]),
        sa.ForeignKeyConstraint(["predecessor_promotion_pk"], [f"{name}.pk"]),
    )


def _page_status(batch_status: str, rows: list[RowMapping]) -> str:
    if batch_status in {"draft", "aborted"}:
        return batch_status
    statuses = {row["status"] for row in rows}
    if "staged" in statuses:
        return "running"
    if statuses & {"conflict", "error"}:
        return "partial"
    return "complete"


def upgrade() -> None:
    # Both tables are rebuilt together. Rebuilding promotionbatch alone with
    # batch_alter_table would drop a parent still referenced by promotion and
    # fails under SQLite's deliberately enabled foreign-key enforcement.
    _create_page_batch_table("promotionbatch_page")
    _create_revision_promotion_table("promotion_page", "promotionbatch_page")

    bind = op.get_bind()
    batches = list(
        bind.execute(sa.text("SELECT * FROM promotionbatch ORDER BY pk")).mappings()
    )
    next_batch_pk = max((batch["pk"] for batch in batches), default=0) + 1

    for batch in batches:
        rows = list(
            bind.execute(
                sa.text(
                    "SELECT * FROM promotion WHERE batch_pk = :batch_pk ORDER BY pk"
                ),
                {"batch_pk": batch["pk"]},
            ).mappings()
        )
        grouped: dict[tuple[object, ...], list[RowMapping]] = defaultdict(list)
        for row in rows:
            grouped[
                (
                    row["page_link_pk"],
                    row["source_page_pk"],
                    row["target_page_pk"],
                    row["target_title"],
                    row["page_number"],
                    row["source_head_revid"],
                    row["anchor_link_pk"],
                )
            ].append(row)

        # A successfully staged batch always has at least one promotion. An
        # empty draft has no page identity to preserve in the new model.
        for position, (key, page_rows) in enumerate(grouped.items()):
            new_batch_pk = batch["pk"] if position == 0 else next_batch_pk
            if position:
                next_batch_pk += 1
            (
                page_link_pk,
                source_page_pk,
                target_page_pk,
                target_title,
                page_number,
                source_head_revid,
                anchor_link_pk,
            ) = key
            source_title = bind.execute(
                sa.text("SELECT title FROM page WHERE pk = :pk"),
                {"pk": source_page_pk},
            ).scalar_one()
            bind.execute(
                sa.text("""
                    INSERT INTO promotionbatch_page (
                        pk, source_site_pk, target_site_pk, index_link_pk,
                        page_link_pk, source_page_pk, target_page_pk,
                        source_title, target_title, page_number,
                        source_head_revid, anchor_link_pk, label, status,
                        created_at
                    ) VALUES (
                        :pk, :source_site_pk, :target_site_pk, :index_link_pk,
                        :page_link_pk, :source_page_pk, :target_page_pk,
                        :source_title, :target_title, :page_number,
                        :source_head_revid, :anchor_link_pk, :label, :status,
                        :created_at
                    )
                    """),
                {
                    "pk": new_batch_pk,
                    "source_site_pk": batch["source_site_pk"],
                    "target_site_pk": batch["target_site_pk"],
                    "index_link_pk": batch["index_link_pk"],
                    "page_link_pk": page_link_pk,
                    "source_page_pk": source_page_pk,
                    "target_page_pk": target_page_pk,
                    "source_title": source_title,
                    "target_title": target_title,
                    "page_number": page_number,
                    "source_head_revid": source_head_revid,
                    "anchor_link_pk": anchor_link_pk,
                    "label": batch["label"],
                    "status": _page_status(batch["status"], page_rows),
                    "created_at": batch["created_at"],
                },
            )
            for row in page_rows:
                bind.execute(
                    sa.text("""
                        INSERT INTO promotion_page (
                            pk, batch_pk, intent, source_revision_pk,
                            predecessor_promotion_pk, base_revid, body, comment,
                            status, pre_push_target_revid, result_revid,
                            error_message, staged_at, pushed_at
                        ) VALUES (
                            :pk, :batch_pk, :intent, :source_revision_pk,
                            :predecessor_promotion_pk, :base_revid, :body, :comment,
                            :status, :pre_push_target_revid, :result_revid,
                            :error_message, :staged_at, :pushed_at
                        )
                        """),
                    {**dict(row), "batch_pk": new_batch_pk},
                )

    op.drop_table("promotion")
    op.drop_table("promotionbatch")
    op.rename_table("promotionbatch_page", "promotionbatch")
    op.rename_table("promotion_page", "promotion")

    for column in (
        "source_site_pk",
        "target_site_pk",
        "index_link_pk",
        "page_link_pk",
        "source_page_pk",
        "target_page_pk",
        "anchor_link_pk",
        "status",
    ):
        op.create_index(f"ix_promotionbatch_{column}", "promotionbatch", [column])
    for column in ("batch_pk", "predecessor_promotion_pk", "status"):
        op.create_index(f"ix_promotion_{column}", "promotion", [column])


def downgrade() -> None:
    # Downgrade retains the one-page batches; it only moves page identity back
    # onto each promotion row and restores the old column names.
    op.create_table(
        "promotionbatch_old",
        sa.Column("pk", sa.Integer(), primary_key=True),
        sa.Column("source_site_pk", sa.Integer(), nullable=False),
        sa.Column("target_site_pk", sa.Integer(), nullable=False),
        sa.Column("index_link_pk", sa.Integer(), nullable=True),
        sa.Column("source_index_title", sa.String(), nullable=False),
        sa.Column("target_index_title", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_site_pk"], ["site.pk"]),
        sa.ForeignKeyConstraint(["target_site_pk"], ["site.pk"]),
        sa.ForeignKeyConstraint(["index_link_pk"], ["indexlink.pk"]),
    )
    op.create_table(
        "promotion_old",
        sa.Column("pk", sa.Integer(), primary_key=True),
        sa.Column("batch_pk", sa.Integer(), nullable=False),
        sa.Column("page_link_pk", sa.Integer(), nullable=True),
        sa.Column("source_page_pk", sa.Integer(), nullable=False),
        sa.Column("target_page_pk", sa.Integer(), nullable=True),
        sa.Column("target_title", sa.String(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("intent", sa.String(), nullable=False),
        sa.Column("source_revision_pk", sa.Integer(), nullable=False),
        sa.Column("source_head_revid", sa.Integer(), nullable=True),
        sa.Column("predecessor_promotion_pk", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["batch_pk"], ["promotionbatch_old.pk"]),
        sa.ForeignKeyConstraint(["source_revision_pk"], ["revision.pk"]),
        sa.ForeignKeyConstraint(["predecessor_promotion_pk"], ["promotion_old.pk"]),
    )

    bind = op.get_bind()
    bind.execute(sa.text("""
            INSERT INTO promotionbatch_old
            SELECT pk, source_site_pk, target_site_pk, index_link_pk,
                   source_title, target_title, label, status,
                   created_at
            FROM promotionbatch
            """))
    bind.execute(sa.text("""
            INSERT INTO promotion_old
            SELECT p.pk, p.batch_pk, b.page_link_pk, b.source_page_pk,
                   b.target_page_pk, b.target_title, b.page_number, p.intent,
                   p.source_revision_pk, b.source_head_revid,
                   p.predecessor_promotion_pk, b.anchor_link_pk, p.base_revid,
                   p.body, p.comment, p.status, p.pre_push_target_revid,
                   p.result_revid, p.error_message, p.staged_at, p.pushed_at
            FROM promotion p JOIN promotionbatch b ON b.pk = p.batch_pk
            """))
    op.drop_table("promotion")
    op.drop_table("promotionbatch")
    op.rename_table("promotionbatch_old", "promotionbatch")
    op.rename_table("promotion_old", "promotion")
    for column in ("index_link_pk", "source_site_pk", "status", "target_site_pk"):
        op.create_index(f"ix_promotionbatch_{column}", "promotionbatch", [column])
    for column in (
        "anchor_link_pk",
        "batch_pk",
        "page_link_pk",
        "predecessor_promotion_pk",
        "source_page_pk",
        "status",
        "target_page_pk",
    ):
        op.create_index(f"ix_promotion_{column}", "promotion", [column])
