"""Key EditJournal, Commit and ProofreadPageMeta to Title rather than Page.

Revision ID: 8e3f1b6d0a27
Revises: 5d2a7c41e9b3
Create Date: 2026-09-24 14:00:00.000000+00:00

Step 2 of splitting Page into Title and WikiPage, for the first three tables
(docs/design/pages-and-existence.md §0). Each is about an *address*, not about
something the wiki holds:

- an EditJournal row is a save, and the first save of an untranscribed page is
  the ordinary case;
- a Commit is how a page comes to exist on the wiki, so it cannot require one;
- ProofreadPageMeta holds the scan, page number and proposed body that make an
  untranscribed page worth opening, and names its owning Index, which the
  fan-out knows about before anyone fetches it.

**No data moves.** Step 1 gave every page a title with the same pk, so each
``page_pk`` value already is the right ``title_pk``. This renames the columns
and points their foreign keys (and ProofreadPageMeta's index reference) at
``title`` -- a rebuild of each table, which ``migration_connection`` allows.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "8e3f1b6d0a27"
down_revision: str | None = "5d2a7c41e9b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _repoint(table: str, old: str, new: str, *, indexed: bool) -> None:
    """Rename ``old`` to ``new`` and point it at ``title`` instead of ``page``.

    Names follow wtbot.model.conventions, so they can be stated rather than
    reflected: fk_<table>_<column>_<target>, ix_<table>_<column>.

    Three separate moves, because alembic's batch mode silently loses a
    foreign key or index created on a column renamed in the same batch --
    the table rebuilds, every row survives, and the constraint is simply
    gone. So: the rename is SQLite's native ``RENAME COLUMN``, which rewrites
    the column's own foreign-key clause and indexes in place; then one batch
    swaps the constraint's target; then the index takes its new name.
    """
    _swap(table, old, new, old_target="page", new_target="title", indexed=indexed)


def _swap(
    table: str,
    old: str,
    new: str,
    *,
    old_target: str,
    new_target: str,
    indexed: bool,
) -> None:
    op.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"')
    with op.batch_alter_table(table) as batch_op:
        batch_op.drop_constraint(f"fk_{table}_{old}_{old_target}", type_="foreignkey")
        batch_op.create_foreign_key(
            f"fk_{table}_{new}_{new_target}", new_target, [new], ["pk"]
        )
    if indexed:
        op.drop_index(f"ix_{table}_{old}", table_name=table)
        op.create_index(f"ix_{table}_{new}", table, [new])


def _restore(table: str, new: str, old: str, *, indexed: bool) -> None:
    _swap(table, new, old, old_target="title", new_target="page", indexed=indexed)


def upgrade() -> None:
    _repoint("editjournal", "page_pk", "title_pk", indexed=True)
    _repoint("commit", "page_pk", "title_pk", indexed=True)
    # The primary key is the page's own identity; not separately indexed.
    _repoint("proofreadpagemeta", "page_pk", "title_pk", indexed=False)
    _repoint("proofreadpagemeta", "index_page_pk", "index_title_pk", indexed=True)


def downgrade() -> None:
    _restore("proofreadpagemeta", "index_title_pk", "index_page_pk", indexed=True)
    _restore("proofreadpagemeta", "title_pk", "page_pk", indexed=False)
    _restore("commit", "title_pk", "page_pk", indexed=True)
    _restore("editjournal", "title_pk", "page_pk", indexed=True)
