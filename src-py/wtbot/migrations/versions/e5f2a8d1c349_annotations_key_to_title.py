"""Key the annotation tables to Title rather than Page.

Revision ID: e5f2a8d1c349
Revises: d7a3c9e5b184
Create Date: 2026-09-24 18:00:00.000000+00:00

Step 2 of the Title/WikiPage split, for ScanAnnotation, BoxRangeLink and
TextTargetAnchor. An annotation is drawn on a title's reference scan: the scan
exists for an untranscribed page (ProofreadPage serves it before anything is
saved), so marking up the page one is about to transcribe must not need a
Page row behind it.

**No data moves.** Every ``page_pk`` value already is the right ``title_pk``
(step 1 gave each page a title with the same pk). Same three moves as
8e3f1b6d0a27, for the same reason: SQLite's native ``RENAME COLUMN`` rewrites
the column's foreign-key clause, unique constraints and indexes in place;
one batch then swaps the constraint's target; the index takes its new name.
Batch mode must not do the rename -- it silently drops constraints created on
a column renamed in the same batch.

The unique constraints (``uq_scan_annotation_page_annotation`` and friends)
keep their names, which do not mention the column.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5f2a8d1c349"
down_revision: str | None = "d7a3c9e5b184"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("scanannotation", "boxrangelink", "texttargetanchor")


def _swap(table: str, old: str, new: str, *, old_target: str, new_target: str) -> None:
    op.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"')
    with op.batch_alter_table(table) as batch_op:
        batch_op.drop_constraint(f"fk_{table}_{old}_{old_target}", type_="foreignkey")
        batch_op.create_foreign_key(
            f"fk_{table}_{new}_{new_target}", new_target, [new], ["pk"]
        )
    op.drop_index(f"ix_{table}_{old}", table_name=table)
    op.create_index(f"ix_{table}_{new}", table, [new])


def upgrade() -> None:
    for table in _TABLES:
        _swap(table, "page_pk", "title_pk", old_target="page", new_target="title")


def downgrade() -> None:
    for table in reversed(_TABLES):
        _swap(table, "title_pk", "page_pk", old_target="title", new_target="page")
