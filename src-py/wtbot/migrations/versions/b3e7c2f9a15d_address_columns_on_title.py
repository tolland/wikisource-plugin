"""Move the address's columns from page to title; drop Page.fetch_error.

Revision ID: b3e7c2f9a15d
Revises: a9d4b7e1f026
Create Date: 2026-09-26 10:00:00.000000+00:00

``namespace_key``, ``fetch_status`` and ``dirty`` describe the address, not the
page the wiki holds: an untranscribed ``Page:`` is fetched-and-absent, and a
title with no page behind it can hold local saves. Each title takes its page's
values (they share a pk); a title with no page keeps the defaults -- unknown
namespace, unfetched, clean.

``fetch_error`` goes rather than moves: nothing ever wrote it.
``history_complete_from_revid`` stays on page, with the Revision rows it
describes.

Native ``ADD``/``DROP COLUMN``; no table is rebuilt. The added NOT NULL
columns carry server defaults, which ADD COLUMN requires, and which the model
declares too.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3e7c2f9a15d"
down_revision: str | None = "a9d4b7e1f026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE title ADD COLUMN namespace_key INTEGER"))
    op.execute(
        sa.text(
            "ALTER TABLE title ADD COLUMN fetch_status VARCHAR(9) NOT NULL "
            "DEFAULT 'unfetched'"
        )
    )
    op.execute(sa.text("ALTER TABLE title ADD COLUMN dirty BOOLEAN NOT NULL DEFAULT 0"))
    op.execute(sa.text("""
        UPDATE title SET
            namespace_key = page.namespace_key,
            fetch_status = page.fetch_status,
            dirty = page.dirty
        FROM page WHERE page.pk = title.pk
        """))
    op.create_index("ix_title_dirty", "title", ["dirty"])

    op.drop_index("ix_page_dirty", table_name="page")
    for column in ("namespace_key", "fetch_status", "dirty", "fetch_error"):
        op.execute(sa.text(f"ALTER TABLE page DROP COLUMN {column}"))


def downgrade() -> None:
    # The columns come back in their old places' shape, with defaults: ADD
    # COLUMN cannot add a NOT NULL column without one.
    op.execute(sa.text("ALTER TABLE page ADD COLUMN namespace_key INTEGER"))
    op.execute(sa.text("ALTER TABLE page ADD COLUMN dirty BOOLEAN NOT NULL DEFAULT 0"))
    op.execute(
        sa.text(
            "ALTER TABLE page ADD COLUMN fetch_status VARCHAR(9) NOT NULL "
            "DEFAULT 'unfetched'"
        )
    )
    op.execute(sa.text("ALTER TABLE page ADD COLUMN fetch_error VARCHAR"))
    op.execute(sa.text("""
        UPDATE page SET
            namespace_key = title.namespace_key,
            fetch_status = title.fetch_status,
            dirty = title.dirty
        FROM title WHERE title.pk = page.pk
        """))
    op.create_index("ix_page_dirty", "page", ["dirty"])

    op.drop_index("ix_title_dirty", table_name="title")
    for column in ("namespace_key", "fetch_status", "dirty"):
        op.execute(sa.text(f"ALTER TABLE title DROP COLUMN {column}"))
