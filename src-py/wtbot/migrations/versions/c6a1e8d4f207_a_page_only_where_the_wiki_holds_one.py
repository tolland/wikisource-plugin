"""A page row only where the wiki holds the page; local_modified_at to title.

Revision ID: c6a1e8d4f207
Revises: b3e7c2f9a15d
Create Date: 2026-09-26 14:00:00.000000+00:00

Step 3 of the Title/WikiPage split. A **placeholder** -- a ``page`` row with no
``revid`` -- stood for a title the wiki does not hold: an untranscribed
``Page:`` the index paginates, or an Index named by a page before it was
fetched. Everything such a row said now lives elsewhere: the address on
``title`` (fetch status, dirty), the pagination in ``proofreadpagemeta``, the
saves in ``editjournal``. So the rows go, and "the wiki holds this page" becomes
row presence.

``local_modified_at`` moves to ``title`` first: it is set by a local save, and
a title with no page can be saved.

A placeholder is deleted only if nothing that means "the wiki holds this page"
refers to it -- a ``revision``, a ``fileblob``, a ``promotionbatch`` source. One
that is referred to contradicts itself (a revision of a page with no revid),
and the migration stops and names it rather than guess which side is wrong.

Downgrade gives every page-less title a placeholder row again, as the old
model's hook did.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6a1e8d4f207"
down_revision: str | None = "b3e7c2f9a15d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLACEHOLDER = "page.revid IS NULL"

_CONTRADICTIONS = """
    SELECT page.pk, page.title FROM page WHERE page.revid IS NULL AND (
        EXISTS (SELECT 1 FROM revision WHERE revision.page_pk = page.pk)
        OR EXISTS (SELECT 1 FROM fileblob WHERE fileblob.page_pk = page.pk)
        OR EXISTS (
            SELECT 1 FROM promotionbatch WHERE promotionbatch.source_page_pk = page.pk
        )
    )
    ORDER BY page.pk
"""


def upgrade() -> None:
    connection = op.get_bind()
    contradictions = connection.execute(sa.text(_CONTRADICTIONS)).all()
    if contradictions:
        listed = ", ".join(f"{pk} {title!r}" for pk, title in contradictions)
        raise RuntimeError(
            "page rows with no revid are still referred to as pages the wiki "
            f"holds (revision, fileblob or promotion source): {listed}. Refetch "
            "them, or delete the referring rows, then migrate again."
        )

    op.execute(sa.text("ALTER TABLE title ADD COLUMN local_modified_at DATETIME"))
    op.execute(sa.text("""
        UPDATE title SET local_modified_at = page.local_modified_at
        FROM page WHERE page.pk = title.pk
        """))
    op.execute(sa.text("ALTER TABLE page DROP COLUMN local_modified_at"))

    op.execute(sa.text(f"DELETE FROM page WHERE {_PLACEHOLDER}"))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE page ADD COLUMN local_modified_at DATETIME"))
    op.execute(sa.text("""
        INSERT INTO page (pk, site_pk, title, content_model)
        SELECT pk, site_pk, title, expected_content_model FROM title
        WHERE NOT EXISTS (SELECT 1 FROM page WHERE page.pk = title.pk)
        """))
    op.execute(sa.text("""
        UPDATE page SET local_modified_at = title.local_modified_at
        FROM title WHERE title.pk = page.pk
        """))
    op.execute(sa.text("ALTER TABLE title DROP COLUMN local_modified_at"))
