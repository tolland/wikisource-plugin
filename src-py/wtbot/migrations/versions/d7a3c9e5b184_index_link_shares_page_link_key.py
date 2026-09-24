"""IndexLink shares PageLink's primary key; PageLink loses index_link_pk.

Revision ID: d7a3c9e5b184
Revises: b41d8e2c7f60
Create Date: 2026-09-24 17:00:00.000000+00:00

Every work *is* a pairing of two ``Index:`` pages, so ``indexlink.pk`` now is
``pagelink.pk`` -- the same shared-key shape as ``page``/``title``. That makes
the old ``page_link_pk`` column and its unique index redundant: one work per
pairing follows from the key.

``pagelink.index_link_pk`` goes: a work's page pairs are derived from each
page's ``ProofreadPageMeta.index_title_pk`` (see
``wtbot.linking.index_link_store.children_of``), so there is no pointer to keep
correct. Dropping it also removes the ``indexlink`` <-> ``pagelink`` foreign
key cycle that every schema comparison warned about.

**Works are renumbered** to their pairing's pk. Nothing else referenced
``indexlink.pk`` except the column being dropped (PromotionBatch lost its copy
in the previous step), so no reference needs rewriting.

**Both tables are rebuilt by hand.** Dropping a column that carries a foreign
key needs a rebuild, and alembic's batch mode rebuilds from reflection --
which cannot see ``uq_pagelink_pair``, an expression index, and would silently
lose the constraint that makes a pairing unique. So the final DDL is stated
here, the expression index included, and ``migration_connection`` provides
the keys-off transaction.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7a3c9e5b184"
down_revision: str | None = "b41d8e2c7f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _origin() -> sa.Column:
    return sa.Column(
        "origin",
        sa.Enum("copy", "title_match", "manual", "reconciled", name="linkorigin"),
        nullable=False,
    )


def _pagelink_indexes() -> None:
    op.create_index("ix_pagelink_local_page_pk", "pagelink", ["local_page_pk"])
    op.create_index("ix_pagelink_remote_page_pk", "pagelink", ["remote_page_pk"])
    # Unique on the unordered pair. Restated by hand: it cannot be reflected.
    op.create_index(
        "uq_pagelink_pair",
        "pagelink",
        [
            sa.text("min(local_page_pk, remote_page_pk)"),
            sa.text("max(local_page_pk, remote_page_pk)"),
        ],
        unique=True,
    )


def _pagelink_table(name: str, *, with_index_link: bool) -> None:
    columns = [
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("local_page_pk", sa.Integer(), nullable=False),
        sa.Column("remote_page_pk", sa.Integer(), nullable=False),
    ]
    constraints = [
        sa.PrimaryKeyConstraint("pk", name="pk_pagelink"),
        sa.ForeignKeyConstraint(
            ["local_page_pk"], ["page.pk"], name="fk_pagelink_local_page_pk_page"
        ),
        sa.ForeignKeyConstraint(
            ["remote_page_pk"], ["page.pk"], name="fk_pagelink_remote_page_pk_page"
        ),
    ]
    if with_index_link:
        columns.append(sa.Column("index_link_pk", sa.Integer(), nullable=True))
        constraints.append(
            sa.ForeignKeyConstraint(
                ["index_link_pk"],
                ["indexlink.pk"],
                name="fk_pagelink_index_link_pk_indexlink",
            )
        )
    op.create_table(
        name,
        *columns,
        _origin(),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        *constraints,
    )


def _replace(old: str, new: str) -> None:
    op.drop_table(old)
    op.rename_table(new, old)


def upgrade() -> None:
    op.create_table(
        "_indexlink_new",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("pk", name="pk_indexlink"),
        sa.ForeignKeyConstraint(
            ["pk"], ["pagelink.pk"], name="fk_indexlink_pk_pagelink"
        ),
    )
    op.execute(sa.text("""
        INSERT INTO _indexlink_new (pk, created_at)
        SELECT page_link_pk, created_at FROM indexlink
        """))
    _replace("indexlink", "_indexlink_new")

    _pagelink_table("_pagelink_new", with_index_link=False)
    op.execute(sa.text("""
        INSERT INTO _pagelink_new (pk, local_page_pk, remote_page_pk, origin, created_at)
        SELECT pk, local_page_pk, remote_page_pk, origin, created_at FROM pagelink
        """))
    _replace("pagelink", "_pagelink_new")
    _pagelink_indexes()


def downgrade() -> None:
    # Works get fresh numbers of their own again, and their pairs point back at
    # them: a pair belongs to the work whose index one of its pages is a child
    # of (the derivation, materialised once), exactly as adoption claimed them.
    op.create_table(
        "_indexlink_old",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("page_link_pk", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("pk", name="pk_indexlink"),
        sa.ForeignKeyConstraint(
            ["page_link_pk"], ["pagelink.pk"], name="fk_indexlink_page_link_pk_pagelink"
        ),
    )
    op.execute(sa.text("""
        INSERT INTO _indexlink_old (pk, page_link_pk, created_at)
        SELECT pk, pk, created_at FROM indexlink
        """))
    _replace("indexlink", "_indexlink_old")
    op.create_index(
        "ix_indexlink_page_link_pk", "indexlink", ["page_link_pk"], unique=True
    )

    _pagelink_table("_pagelink_old", with_index_link=True)
    op.execute(sa.text("""
        INSERT INTO _pagelink_old
            (pk, local_page_pk, remote_page_pk, index_link_pk, origin, created_at)
        SELECT p.pk, p.local_page_pk, p.remote_page_pk,
               (SELECT w.pk FROM indexlink w
                JOIN pagelink wp ON wp.pk = w.page_link_pk
                JOIN proofreadpagemeta m
                  ON m.title_pk IN (p.local_page_pk, p.remote_page_pk)
                WHERE m.index_title_pk IN (wp.local_page_pk, wp.remote_page_pk)
                  AND w.page_link_pk != p.pk
                ORDER BY w.pk LIMIT 1),
               p.origin, p.created_at
        FROM pagelink p
        """))
    _replace("pagelink", "_pagelink_old")
    _pagelink_indexes()
    op.create_index("ix_pagelink_index_link_pk", "pagelink", ["index_link_pk"])
