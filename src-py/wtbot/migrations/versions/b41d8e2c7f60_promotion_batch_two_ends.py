"""Reduce PromotionBatch to its two ends: a source page and a target title.

Revision ID: b41d8e2c7f60
Revises: 8e3f1b6d0a27
Create Date: 2026-09-24 16:00:00.000000+00:00

Everything else the batch copied in is implied by those two and is resolved
when needed (``wtbot.promotion.promotion_store.batch_ends``): the two sites,
the two titles, the page correspondence, the tracked work and the page
number. ``source_head_revid`` and ``anchor_link_pk`` stay -- they record what
was reviewed, which is the point of freezing anything.

``target_page_pk`` becomes ``target_title_pk`` and loses its null. A batch
staged as a create had no target page and so no pk, only a title string; the
title it named is created here, at the same address, with the source page's
content model as its expected one (a promotion copies the source's content).

**Rebuilt by hand rather than through batch mode.** This table's constraints
are named ``fk_promotionbatch_page_...`` in a migrated database -- a leftover
from an earlier table name -- and ``fk_promotionbatch_...`` in one restored
from the models. Dropping them by name would work on one and fail on the
other; SQLite's own rebuild procedure (new table, copy, drop, rename) does not
care what the old ones were called, and leaves conventional names behind.
``migration_connection`` supplies the keys-off transaction it needs.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b41d8e2c7f60"
down_revision: str | None = "8e3f1b6d0a27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEPT = ("source_head_revid", "anchor_link_pk", "label", "status", "created_at")
_INDEXED_AFTER = ("source_page_pk", "target_title_pk", "anchor_link_pk", "status")
_INDEXED_BEFORE = (
    "source_site_pk",
    "target_site_pk",
    "index_link_pk",
    "page_link_pk",
    "source_page_pk",
    "target_page_pk",
    "anchor_link_pk",
    "status",
)


def _kept_columns() -> list[sa.Column]:
    return [
        sa.Column("source_head_revid", sa.Integer(), nullable=True),
        sa.Column("anchor_link_pk", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    ]


def _replace(new_table: str) -> None:
    op.drop_table("promotionbatch")
    op.rename_table(new_table, "promotionbatch")


def upgrade() -> None:
    # A title for every target that had none: the batches staged as creates.
    # Grouped, so two batches aimed at one address make one title.
    op.execute(sa.text("""
        INSERT INTO title (site_pk, title, expected_content_model)
        SELECT b.target_site_pk, b.target_title,
               MIN(COALESCE(p.content_model, 'wikitext'))
        FROM promotionbatch b JOIN page p ON p.pk = b.source_page_pk
        WHERE b.target_page_pk IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM title t
              WHERE t.site_pk = b.target_site_pk AND t.title = b.target_title)
        GROUP BY b.target_site_pk, b.target_title
        """))

    op.create_table(
        "_promotionbatch_new",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("source_page_pk", sa.Integer(), nullable=False),
        sa.Column("target_title_pk", sa.Integer(), nullable=False),
        *_kept_columns(),
        sa.PrimaryKeyConstraint("pk", name="pk_promotionbatch"),
        sa.ForeignKeyConstraint(
            ["source_page_pk"],
            ["page.pk"],
            name="fk_promotionbatch_source_page_pk_page",
        ),
        sa.ForeignKeyConstraint(
            ["target_title_pk"],
            ["title.pk"],
            name="fk_promotionbatch_target_title_pk_title",
        ),
        sa.ForeignKeyConstraint(
            ["anchor_link_pk"],
            ["revisionlink.pk"],
            name="fk_promotionbatch_anchor_link_pk_revisionlink",
        ),
    )
    kept = ", ".join(_KEPT)
    op.execute(sa.text(f"""
        INSERT INTO _promotionbatch_new (pk, source_page_pk, target_title_pk, {kept})
        SELECT b.pk, b.source_page_pk,
               COALESCE(b.target_page_pk,
                        (SELECT t.pk FROM title t
                         WHERE t.site_pk = b.target_site_pk
                           AND t.title = b.target_title)),
               {", ".join(f"b.{c}" for c in _KEPT)}
        FROM promotionbatch b
        """))
    _replace("_promotionbatch_new")
    for column in _INDEXED_AFTER:
        op.create_index(f"ix_promotionbatch_{column}", "promotionbatch", [column])


def downgrade() -> None:
    # The dropped columns are all derivable, so they come back filled -- except
    # index_link_pk and page_link_pk, which were only ever a copy and come back
    # null (the old schema allowed it). target_page_pk is the target's page
    # when the wiki holds one, as it was.
    op.create_table(
        "_promotionbatch_old",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("source_site_pk", sa.Integer(), nullable=False),
        sa.Column("target_site_pk", sa.Integer(), nullable=False),
        sa.Column("index_link_pk", sa.Integer(), nullable=True),
        sa.Column("page_link_pk", sa.Integer(), nullable=True),
        sa.Column("source_page_pk", sa.Integer(), nullable=False),
        sa.Column("target_page_pk", sa.Integer(), nullable=True),
        sa.Column("source_title", sa.String(), nullable=False),
        sa.Column("target_title", sa.String(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        *_kept_columns(),
        sa.PrimaryKeyConstraint("pk", name="pk_promotionbatch"),
        sa.ForeignKeyConstraint(
            ["source_site_pk"],
            ["site.pk"],
            name="fk_promotionbatch_source_site_pk_site",
        ),
        sa.ForeignKeyConstraint(
            ["target_site_pk"],
            ["site.pk"],
            name="fk_promotionbatch_target_site_pk_site",
        ),
        sa.ForeignKeyConstraint(
            ["index_link_pk"],
            ["indexlink.pk"],
            name="fk_promotionbatch_index_link_pk_indexlink",
        ),
        sa.ForeignKeyConstraint(
            ["page_link_pk"],
            ["pagelink.pk"],
            name="fk_promotionbatch_page_link_pk_pagelink",
        ),
        sa.ForeignKeyConstraint(
            ["source_page_pk"],
            ["page.pk"],
            name="fk_promotionbatch_source_page_pk_page",
        ),
        sa.ForeignKeyConstraint(
            ["target_page_pk"],
            ["page.pk"],
            name="fk_promotionbatch_target_page_pk_page",
        ),
        sa.ForeignKeyConstraint(
            ["anchor_link_pk"],
            ["revisionlink.pk"],
            name="fk_promotionbatch_anchor_link_pk_revisionlink",
        ),
    )
    kept = ", ".join(_KEPT)
    op.execute(sa.text(f"""
        INSERT INTO _promotionbatch_old (
            pk, source_site_pk, target_site_pk, source_page_pk, target_page_pk,
            source_title, target_title, page_number, {kept})
        SELECT b.pk, source.site_pk, target.site_pk, b.source_page_pk,
               (SELECT p.pk FROM page p WHERE p.pk = b.target_title_pk),
               source.title, target.title,
               (SELECT m.page_number FROM proofreadpagemeta m
                WHERE m.title_pk = b.source_page_pk),
               {", ".join(f"b.{c}" for c in _KEPT)}
        FROM promotionbatch b
        JOIN page source ON source.pk = b.source_page_pk
        JOIN title target ON target.pk = b.target_title_pk
        """))
    _replace("_promotionbatch_old")
    for column in _INDEXED_BEFORE:
        op.create_index(f"ix_promotionbatch_{column}", "promotionbatch", [column])
